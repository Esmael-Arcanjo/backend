"""Market segment configuration for the CRM: lead fields, default pipeline and lead sources."""

_BASE_STAGES = [("qualificacao", "Qualificação", 10), ("proposta", "Proposta", 50),
                ("negociacao", "Negociação", 75), ("fechamento", "Fechamento", 90)]


def _stages(items):
    return [{"key": k, "name": n, "probability": p} for k, n, p in items]


SEGMENT_CONFIG = {
    "agro": {
        "lead_fields": [{"key": "propriedade", "label": "Propriedade", "type": "text"},
                        {"key": "hectares", "label": "Área (hectares)", "type": "number"},
                        {"key": "cultura", "label": "Cultura principal", "type": "text"},
                        {"key": "safra", "label": "Safra de interesse", "type": "text"}],
        "stages": _stages([("visita", "Visita técnica", 10), ("amostra", "Amostra/teste", 35),
                           ("proposta", "Proposta", 60), ("negociacao", "Negociação", 80)]),
        "sources": ["Feira agro", "Cooperativa", "Indicação", "Representante", "Site"],
    },
    "educacao": {
        "lead_fields": [{"key": "curso", "label": "Curso de interesse", "type": "text"},
                        {"key": "modalidade", "label": "Modalidade", "type": "text"},
                        {"key": "responsavel", "label": "Responsável", "type": "text"}],
        "stages": _stages([("interesse", "Interesse", 10), ("visita", "Visita/aula experimental", 40),
                           ("matricula", "Pré-matrícula", 75), ("pagamento", "Pagamento da matrícula", 90)]),
        "sources": ["Site", "Redes sociais", "Indicação", "Evento", "Campanha"],
    },
    "hotelaria": {
        "lead_fields": [{"key": "checkin", "label": "Check-in previsto", "type": "date"},
                        {"key": "noites", "label": "Noites", "type": "number"},
                        {"key": "hospedes", "label": "Hóspedes", "type": "number"},
                        {"key": "tipo_evento", "label": "Tipo (lazer/corporativo/evento)", "type": "text"}],
        "stages": _stages([("cotacao", "Cotação", 20), ("proposta", "Proposta enviada", 50),
                           ("pre_reserva", "Pré-reserva", 75), ("garantia", "Garantia de reserva", 90)]),
        "sources": ["OTA", "Site", "Agência", "Corporativo", "Telefone"],
    },
    "juridico": {
        "lead_fields": [{"key": "area_direito", "label": "Área do direito", "type": "text"},
                        {"key": "tipo_demanda", "label": "Tipo de demanda", "type": "text"},
                        {"key": "urgencia", "label": "Urgência", "type": "text"}],
        "stages": _stages([("triagem", "Triagem", 10), ("consulta", "Consulta inicial", 35),
                           ("honorarios", "Proposta de honorários", 65), ("contrato", "Contrato", 90)]),
        "sources": ["Indicação", "Site", "OAB", "Parceiro", "Redes sociais"],
    },
    "logistica": {
        "lead_fields": [{"key": "origem", "label": "Origem", "type": "text"},
                        {"key": "destino", "label": "Destino", "type": "text"},
                        {"key": "volume_mensal", "label": "Volume mensal (ton)", "type": "number"},
                        {"key": "tipo_carga", "label": "Tipo de carga", "type": "text"}],
        "stages": _stages([("cotacao", "Cotação de frete", 20), ("teste", "Embarque teste", 45),
                           ("proposta", "Proposta de contrato", 70), ("negociacao", "Negociação", 85)]),
        "sources": ["Prospecção ativa", "Indicação", "Site", "Licitação"],
    },
    "servicos": {
        "lead_fields": [{"key": "servico", "label": "Serviço desejado", "type": "text"},
                        {"key": "prazo", "label": "Prazo desejado", "type": "date"}],
        "stages": _stages(_BASE_STAGES),
        "sources": ["Site", "Indicação", "Redes sociais", "Google"],
    },
    "saude": {
        "lead_fields": [{"key": "especialidade", "label": "Especialidade", "type": "text"},
                        {"key": "convenio", "label": "Convênio", "type": "text"},
                        {"key": "unidade", "label": "Unidade", "type": "text"}],
        "stages": _stages([("contato", "Primeiro contato", 15), ("avaliacao", "Avaliação", 45),
                           ("orcamento", "Orçamento", 70), ("agendamento", "Agendamento", 90)]),
        "sources": ["Site", "Convênio", "Indicação médica", "Redes sociais"],
    },
    "comercio": {
        "lead_fields": [{"key": "segmento_loja", "label": "Categoria de interesse", "type": "text"},
                        {"key": "canal", "label": "Canal preferido", "type": "text"}],
        "stages": _stages(_BASE_STAGES),
        "sources": ["Loja física", "E-commerce", "WhatsApp", "Indicação"],
    },
}


def get_segment_config(segment: str) -> dict:
    return SEGMENT_CONFIG[segment]


def validate_custom_fields(segment: str, values: dict) -> dict:
    allowed = {f["key"]: f["type"] for f in SEGMENT_CONFIG[segment]["lead_fields"]}
    clean = {}
    for key, value in values.items():
        if key not in allowed:
            raise ValueError(f"Campo '{key}' não existe para o segmento")
        if value in (None, ""):
            continue
        if allowed[key] == "number" and not isinstance(value, (int, float)):
            raise ValueError(f"Campo '{key}' deve ser numérico")
        if allowed[key] in {"text", "date"} and (not isinstance(value, str) or len(value) > 200):
            raise ValueError(f"Campo '{key}' inválido")
        clean[key] = value
    return clean
