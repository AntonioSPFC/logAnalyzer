"""CallId validation for the Call Analysis Dashboard."""

import re


def validate_call_id(call_id: str) -> tuple[bool, str | None]:
    """Validate CallId format.

    A valid CallId is exactly 16 hexadecimal characters (0-9, a-f, A-F).

    Returns:
        Tuple of (is_valid, error_message).
        error_message is None when valid.
    """
    if not call_id or not call_id.strip():
        return False, "CallId não pode ser vazio."

    call_id = call_id.strip()

    if len(call_id) != 16:
        return False, f"CallId deve ter exatamente 16 caracteres (recebido: {len(call_id)})."

    if not re.fullmatch(r'[0-9a-fA-F]{16}', call_id):
        return False, "CallId deve conter apenas caracteres hexadecimais (0-9, a-f)."

    return True, None
