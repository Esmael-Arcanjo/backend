import re


def _cpf_ok(d: str) -> bool:
    if len(d) != 11 or d == d[0] * 11:
        return False
    for n in (9, 10):
        s = sum(int(d[i]) * (n + 1 - i) for i in range(n))
        if (s * 10 % 11) % 10 != int(d[n]):
            return False
    return True


def _cnpj_ok(d: str) -> bool:
    if len(d) != 14 or d == d[0] * 14:
        return False
    for n in (12, 13):
        weights = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2][13 - n:]
        s = sum(int(d[i]) * weights[i] for i in range(n))
        r = s % 11
        if (0 if r < 2 else 11 - r) != int(d[n]):
            return False
    return True


def valid_document(v: str) -> str:
    """Returns CPF/CNPJ digits or raises ValueError (used as a pydantic validator)."""
    digits = re.sub(r"\D", "", v or "")
    if not (_cpf_ok(digits) or _cnpj_ok(digits)):
        raise ValueError("Informe um CPF ou CNPJ válido")
    return digits
