"""Flask application for the Call Analysis Dashboard."""

import os
from flask import Flask, render_template, request, jsonify, redirect, url_for

from dashboard.validators import validate_call_id
from dashboard.store import CurationStore


def create_app(config=None):
    """Application factory for the Call Analysis Dashboard."""
    app = Flask(__name__)

    # Default configuration
    app.config.setdefault('LOG_DIRECTORY', os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'logs'))
    app.config.setdefault('DB_PATH', os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'curation.db'))

    if config:
        app.config.update(config)

    # Initialize store
    store = CurationStore(app.config['DB_PATH'])

    def _get_log_files():
        """List available log files in the configured directory."""
        log_dir = app.config['LOG_DIRECTORY']
        if not os.path.isdir(log_dir):
            return []
        files = []
        for f in sorted(os.listdir(log_dir), reverse=True):
            full_path = os.path.join(log_dir, f)
            if os.path.isfile(full_path):
                if f.endswith('.log') or f.endswith('.gz') or 'olos-ai-orchestrator' in f:
                    files.append(f)
        return files

    @app.route('/')
    def index():
        log_files = _get_log_files()
        return render_template('search.html', log_files=log_files)

    @app.route('/analyze', methods=['POST'])
    def analyze():
        call_id = request.form.get('call_id', '').strip()
        log_file = request.form.get('log_file', '').strip()

        is_valid, error = validate_call_id(call_id)
        if not is_valid:
            log_files = _get_log_files()
            return render_template('search.html', error=error, log_files=log_files), 400

        from log_analyzer.apps.call_parser import CallLogParser
        parser = CallLogParser(app.config['LOG_DIRECTORY'])

        # If a specific file was selected, only search that file
        if log_file:
            file_path = os.path.join(app.config['LOG_DIRECTORY'], log_file)
            if not os.path.isfile(file_path):
                log_files = _get_log_files()
                return render_template('search.html', error=f"Arquivo '{log_file}' não encontrado.", log_files=log_files), 404
            lines = parser._filter_lines(call_id, file_path)
            if not lines:
                log_files = _get_log_files()
                return render_template('search.html', error=f"CallId '{call_id}' não encontrado no arquivo '{log_file}'.", log_files=log_files), 404
            call_data = parser._parse_lines(call_id, lines)
        else:
            call_data = parser.parse(call_id)

        if call_data is None:
            log_files = _get_log_files()
            return render_template('search.html', error=f"CallId '{call_id}' não encontrado nos arquivos de log.", log_files=log_files), 404

        report = store.get_report(call_id)
        return render_template('analysis.html', call=call_data, report=report)

    @app.route('/analyze/<call_id>')
    def analyze_direct(call_id):
        is_valid, error = validate_call_id(call_id)
        if not is_valid:
            log_files = _get_log_files()
            return render_template('search.html', error=error, log_files=log_files), 400

        from log_analyzer.apps.call_parser import CallLogParser
        parser = CallLogParser(app.config['LOG_DIRECTORY'])
        call_data = parser.parse(call_id)

        if call_data is None:
            log_files = _get_log_files()
            return render_template('search.html', error=f"CallId '{call_id}' não encontrado nos arquivos de log.", log_files=log_files), 404

        report = store.get_report(call_id)
        return render_template('analysis.html', call=call_data, report=report)

    @app.route('/reports')
    def reports():
        all_reports = store.list_reports()
        return render_template('reports.html', reports=all_reports)

    @app.route('/reports/save', methods=['POST'])
    def save_report():
        call_id = request.form.get('call_id', '').strip()
        report_text = request.form.get('report_text', '').strip()

        if not call_id:
            return jsonify({"error": "CallId é obrigatório."}), 400
        if not report_text:
            return jsonify({"error": "O texto do relatório não pode ser vazio."}), 400

        report = store.save_report(call_id, report_text)
        return jsonify({
            "status": "success",
            "message": "Relatório salvo com sucesso.",
            "call_id": report.call_id,
            "modified_at": report.modified_at.isoformat(),
        })

    @app.route('/reports/export')
    def export_reports():
        exported = store.export_reports()
        return jsonify(exported)

    return app


if __name__ == '__main__':
    app = create_app()
    app.run(debug=True, port=5000)
