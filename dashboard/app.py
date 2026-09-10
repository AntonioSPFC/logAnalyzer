"""Flask application for the Call Analysis Dashboard."""

import os
from flask import Flask, render_template, request, jsonify, redirect, url_for

from dashboard.validators import validate_call_id
from dashboard.store import CurationStore
from dashboard.flow_stages import carregar_estagios


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

    def _get_flow_files():
        """List available Studio flow JSON files in the configured directory."""
        log_dir = app.config['LOG_DIRECTORY']
        if not os.path.isdir(log_dir):
            return []
        files = []
        for f in sorted(os.listdir(log_dir)):
            full_path = os.path.join(log_dir, f)
            if os.path.isfile(full_path) and f.endswith('.json'):
                files.append(f)
        return files

    @app.route('/')
    def index():
        log_files = _get_log_files()
        flow_files = _get_flow_files()
        return render_template('search.html', log_files=log_files, flow_files=flow_files)

    @app.route('/analyze', methods=['POST'])
    def analyze():
        call_id = request.form.get('call_id', '').strip()
        log_file = request.form.get('log_file', '').strip()
        flow_file = request.form.get('flow_file', '').strip()

        is_valid, error = validate_call_id(call_id)
        if not is_valid:
            log_files = _get_log_files()
            return render_template('search.html', error=error, log_files=log_files, flow_files=_get_flow_files()), 400

        from log_analyzer.apps.call_parser import CallLogParser
        parser = CallLogParser(app.config['LOG_DIRECTORY'])

        # If a specific file was selected, only search that file
        if log_file:
            file_path = os.path.join(app.config['LOG_DIRECTORY'], log_file)
            if not os.path.isfile(file_path):
                log_files = _get_log_files()
                return render_template('search.html', error=f"Arquivo '{log_file}' não encontrado.", log_files=log_files, flow_files=_get_flow_files()), 404
            lines = parser._filter_lines(call_id, file_path)
            if not lines:
                log_files = _get_log_files()
                return render_template('search.html', error=f"CallId '{call_id}' não encontrado no arquivo '{log_file}'.", log_files=log_files, flow_files=_get_flow_files()), 404
            call_data = parser._parse_lines(call_id, lines)
        else:
            call_data = parser.parse(call_id)

        if call_data is None:
            log_files = _get_log_files()
            return render_template('search.html', error=f"CallId '{call_id}' não encontrado nos arquivos de log.", log_files=log_files, flow_files=_get_flow_files()), 404

        # Load defined flow stages when a valid flow file was selected.
        flow_stages = []
        if flow_file:
            flow_path = os.path.join(app.config['LOG_DIRECTORY'], flow_file)
            if os.path.isfile(flow_path):
                flow_stages = carregar_estagios(flow_path)

        report = store.get_report(call_id)
        return render_template('analysis.html', call=call_data, report=report, flow_stages=flow_stages)

    @app.route('/analyze/<call_id>')
    def analyze_direct(call_id):
        is_valid, error = validate_call_id(call_id)
        if not is_valid:
            log_files = _get_log_files()
            return render_template('search.html', error=error, log_files=log_files, flow_files=_get_flow_files()), 400

        from log_analyzer.apps.call_parser import CallLogParser
        parser = CallLogParser(app.config['LOG_DIRECTORY'])
        call_data = parser.parse(call_id)

        if call_data is None:
            log_files = _get_log_files()
            return render_template('search.html', error=f"CallId '{call_id}' não encontrado nos arquivos de log.", log_files=log_files, flow_files=_get_flow_files()), 404

        report = store.get_report(call_id)
        return render_template('analysis.html', call=call_data, report=report, flow_stages=[])

    def _validate_identificador_fase2(identificador):
        """Simple, self-contained validation for the Fase 2 identifier.

        The Fase 2 identifier is free-form text (1..256 chars) and must not be
        empty or whitespace-only. It is intentionally NOT the 16-char hex CallId
        validated by validate_call_id.
        """
        if not identificador or identificador.isspace():
            return False, "O identificador não pode ser vazio."
        if len(identificador) > 256:
            return False, "O identificador deve conter entre 1 e 256 caracteres."
        return True, None

    # Constant, safe message shown whenever the fail-closed policy suppresses
    # the secure view. It never reveals raw content.
    _MSG_SANITIZACAO_SUPRIMIDA = (
        "A análise foi concluída, mas a visão segura foi suprimida pela "
        "política fail-closed: há conteúdo sensível que não pôde ser "
        "integralmente sanitizado."
    )

    @app.route('/fase2')
    def fase2():
        log_files = _get_log_files()
        return render_template('fase2_search.html', log_files=log_files)

    @app.route('/analyze-fase2', methods=['POST'])
    def analyze_fase2():
        identificador = request.form.get('identificador', '').strip()
        vpl_file = request.form.get('vpl_file', '').strip()
        ork_file = request.form.get('ork_file', '').strip()

        is_valid, error = _validate_identificador_fase2(identificador)
        if not is_valid:
            log_files = _get_log_files()
            return render_template(
                'fase2_search.html', error=error, log_files=log_files
            ), 400

        from log_analyzer.core.modelos import ArquivoSelecionado

        selecao = []
        if vpl_file:
            selecao.append(ArquivoSelecionado(
                os.path.join(app.config['LOG_DIRECTORY'], vpl_file), "VPL"
            ))
        if ork_file:
            selecao.append(ArquivoSelecionado(
                os.path.join(app.config['LOG_DIRECTORY'], ork_file), "ORK"
            ))

        if not selecao:
            log_files = _get_log_files()
            return render_template(
                'fase2_search.html',
                error="Selecione ao menos um arquivo (VPL ou ORK).",
                log_files=log_files,
            ), 400

        from log_analyzer.core.bootstrap import criar_registro_padrao
        from log_analyzer.core.pipeline_fase2 import PipelineFase2
        from log_analyzer.core.excecoes import (
            ErroDeIdentificador,
            ErroDeSanitizacao,
        )

        try:
            resultado = PipelineFase2(criar_registro_padrao()).executar(
                tuple(selecao), identificador
            )
        except ErroDeIdentificador as erro:
            log_files = _get_log_files()
            return render_template(
                'fase2_search.html', error=erro.mensagem, log_files=log_files
            ), 400
        except ErroDeSanitizacao:
            # Fail-closed: suppress everything and show only the safe message.
            return render_template(
                'fase2_result.html',
                sanitizacao_suprimida=True,
                mensagem=_MSG_SANITIZACAO_SUPRIMIDA,
            ), 200
        except Exception:
            # Any unexpected pipeline failure is treated fail-closed too.
            return render_template(
                'fase2_result.html',
                sanitizacao_suprimida=True,
                mensagem=_MSG_SANITIZACAO_SUPRIMIDA,
            ), 200

        from log_analyzer.cli.apresentacao import renderizar_resultado
        texto = renderizar_resultado(resultado)
        return render_template(
            'fase2_result.html',
            sanitizacao_suprimida=False,
            resultado=resultado,
            texto=texto,
        ), 200

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
