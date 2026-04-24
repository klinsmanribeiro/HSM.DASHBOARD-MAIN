from flask import Flask, render_template, jsonify, request, session, redirect, url_for
from datetime import datetime
import requests
import time
import os
from collections import deque
from dotenv import load_dotenv

load_dotenv()  # Carregar variáveis do arquivo .env

app = Flask(__name__)

# Secret key para sessions
app.secret_key = os.getenv("SECRET_KEY", "dev-key-change-in-production")

# Ler variáveis do ambiente (.env)
API_BASE = os.getenv("API_BASE", "")
ORIGIN = os.getenv("ORIGIN", "")
API_TOKEN = os.getenv("API_TOKEN", "")

HEADERS = {"Authorization": API_TOKEN}

PAGE_SIZE = 50

# Controle de rate limit — janela deslizante de 60 segundos
request_times = deque()
RATE_LIMIT_PER_MINUTE = 10
rate_limit_hits = 0

# Histórico de erros de rate limit
api_rate_limit_history = deque(maxlen=100)  # Últimos 100 erros
api_rate_limit_count = 0

STATUS_MAP = {
    "ERROR": "Erro", "SENT": "Enviado", "DELIVERED": "Entregue",
    "READ": "Lido", "FAILED": "Falhou", "PENDING": "Pendente",
    "QUEUED": "Na fila", "ACCEPTED": "Aceito", "UNDELIVERED": "Não entregue",
    "ANSWERED": "Respondido",
}

STATUS_COLOR = {
    "ERROR": "error", "FAILED": "error", "UNDELIVERED": "error",
    "SENT": "sent", "DELIVERED": "delivered", "READ": "read",
    "PENDING": "pending", "QUEUED": "pending", "ACCEPTED": "sent",
    "ANSWERED": "answered",
}

def translate_status(status):
    return STATUS_MAP.get(status.upper(), status) if status else "—"

def status_class(status):
    return STATUS_COLOR.get(status.upper(), "pending") if status else "pending"

def format_datetime(ts):
    if not ts:
        return "—"
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        local = dt.astimezone()
        return local.strftime("%d/%m/%Y %H:%M:%S")
    except:
        return ts

def check_rate_limit():
    global rate_limit_hits, api_rate_limit_count
    now = time.time()
    while request_times and request_times[0] < now - 60:
        request_times.popleft()
    count = len(request_times)
    if count >= RATE_LIMIT_PER_MINUTE:
        rate_limit_hits += 1
        api_rate_limit_count += 1
        # Registrar no histórico quando o limite local é acionado
        api_rate_limit_history.append({
            "timestamp": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
            "status_code": 429,
            "message": f"Rate limit local: {RATE_LIMIT_PER_MINUTE} req/min atingido"
        })
        return False, rate_limit_hits, count
    request_times.append(now)
    return True, rate_limit_hits, count + 1

@app.route("/")
def index():
    today = datetime.now().strftime("%Y-%m-%d")
    user = session.get('user', {})
    return render_template("index.html", today=today, user=user)

@app.route("/api/hsm/data")
def fetch_data():
    global rate_limit_hits
    start = request.args.get("startDate", datetime.now().strftime("%Y-%m-%d"))
    end = request.args.get("endDate", datetime.now().strftime("%Y-%m-%d"))
    template_filter = request.args.get("template", "")
    page = int(request.args.get("page", 1))

    allowed, hits, req_count = check_rate_limit()
    if not allowed:
        return jsonify({
            "error": f"Limite de {RATE_LIMIT_PER_MINUTE} requisições/min atingido. Aguarde.",
            "rate_limit_hit": True,
            "rate_limit_hits": hits,
            "alert": hits % 10 == 0,
            "records": [], "templates": [], "pagination": {}, "stats": {}
        }), 429

    try:
        url = f"{API_BASE}?origin={ORIGIN}&startDate={start}&endDate={end}"
        print(f"DEBUG: Fazendo requisição para: {url}")  # Debug
        resp = requests.get(url, headers=HEADERS, timeout=240)
        print(f"DEBUG: Status code: {resp.status_code}")  # Debug
        print(f"DEBUG: Content type: {resp.headers.get('content-type')}")  # Debug
        if resp.status_code != 200:
            print(f"DEBUG: Response text: {resp.text[:500]}")  # Debug

        if resp.status_code == 401:
            return jsonify({"error": "Não autorizado (401): token inválido ou expirado.", "records": [], "templates": [], "pagination": {}, "stats": {}}), 200
        if resp.status_code == 403:
            return jsonify({"error": "Acesso negado (403): sem permissão.", "records": [], "templates": [], "pagination": {}, "stats": {}}), 200
        if resp.status_code == 404:
            return jsonify({"error": "Não encontrado (404): verifique a URL da API.", "records": [], "templates": [], "pagination": {}, "stats": {}}), 200
        if resp.status_code == 429:
            global api_rate_limit_count
            api_rate_limit_count += 1
            api_rate_limit_history.append({
                "timestamp": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
                "status_code": 429,
                "message": "Meta API Error: 130429 - (#130429) Rate limit hit"
            })
            return jsonify({
                "error": "API externa retornou rate limit (429). Aguarde antes de tentar novamente.",
                "rate_limit_hit": True, "rate_limit_hits": api_rate_limit_count,
                "alert": api_rate_limit_count > 10,
                "api_rate_limit_count": api_rate_limit_count,
                "records": [], "templates": [], "pagination": {}, "stats": {}
            }), 200
        if resp.status_code >= 500:
            return jsonify({"error": f"Erro no servidor da API ({resp.status_code}).", "records": [], "templates": [], "pagination": {}, "stats": {}}), 200

        resp.raise_for_status()
        raw = resp.json()

    except requests.exceptions.Timeout:
        return jsonify({"error": "Tempo limite: API não respondeu em 15s.", "records": [], "templates": [], "pagination": {}, "stats": {}}), 200
    except requests.exceptions.ConnectionError:
        return jsonify({"error": "Falha de conexão. Verifique sua internet.", "records": [], "templates": [], "pagination": {}, "stats": {}}), 200
    except Exception as e:
        return jsonify({"error": f"Erro inesperado: {str(e)}", "records": [], "templates": [], "pagination": {}, "stats": {}}), 200

    all_records = raw if isinstance(raw, list) else raw.get("data", raw.get("records", [raw] if isinstance(raw, dict) else []))
    templates = sorted(set(r.get("template.name", "") for r in all_records if r.get("template.name")))

    if template_filter:
        all_records = [r for r in all_records if r.get("template.name") == template_filter]

    processed = []
    for r in all_records:
        st = r.get("status", "")
        processed.append({
            "timestamp": format_datetime(r.get("timestamp")),
            "key": r.get("key", "—"),
            "template_name": r.get("template.name", "—"),
            "status": translate_status(st),
            "status_class": status_class(st),
            "reason": r.get("reason", "—") or "—",
            "flow_id": r.get("parameters.flowId", "—") or "—",
            "agent_id": r.get("parameters.agentId", "—") or "—",
            "answer": r.get("parameters.answer", "—") or "—",
            "conversation_id": r.get("parameters.conversationId", "—") or "—",
        })

    stats = {
        "total": len(processed),
        "erros": sum(1 for p in processed if p["status_class"] == "error"),
        "entregues": sum(1 for p in processed if p["status_class"] == "delivered"),
        "enviados": sum(1 for p in processed if p["status_class"] == "sent"),
        "lidos": sum(1 for p in processed if p["status_class"] == "read"),
        "pendentes": sum(1 for p in processed if p["status_class"] == "pending"),
    }
    
    # Calcular respondidos
    stats["respondidos"] = sum(1 for p in processed if p["status_class"] == "answered")
    
    # Calcular percentuais
    total = stats["total"]
    if total > 0:
        stats["pct_erros"] = round((stats["erros"] / total) * 100, 1)
        stats["pct_entregues"] = round((stats["entregues"] / total) * 100, 1)
        stats["pct_enviados"] = round((stats["enviados"] / total) * 100, 1)
        stats["pct_lidos"] = round((stats["lidos"] / total) * 100, 1)
        stats["pct_sucesso"] = round(((total - stats["erros"]) / total) * 100, 1)
        stats["pct_respondidos"] = round((stats["respondidos"] / total) * 100, 1)
    else:
        stats["pct_erros"] = stats["pct_entregues"] = stats["pct_enviados"] = stats["pct_lidos"] = stats["pct_sucesso"] = stats["pct_respondidos"] = 0
    
    # Distribuição por minuto (útil para análise de picos)
    minute_data = {}
    for p in processed:
        try:
            ts_str = p["timestamp"]
            if ts_str and ts_str != "—":
                minute_key = ts_str[:16]  # YYYY-MM-DD HH:MM
                if minute_key not in minute_data:
                    minute_data[minute_key] = {"total": 0, "erros": 0, "enviados": 0, "entregues": 0, "lidos": 0, "respondidos": 0}
                minute_data[minute_key]["total"] += 1
                if p["status_class"] == "error":
                    minute_data[minute_key]["erros"] += 1
                elif p["status_class"] == "sent":
                    minute_data[minute_key]["enviados"] += 1
                elif p["status_class"] == "delivered":
                    minute_data[minute_key]["entregues"] += 1
                elif p["status_class"] == "read":
                    minute_data[minute_key]["lidos"] += 1
                if p["status_class"] == "answered":
                    minute_data[minute_key]["respondidos"] += 1
        except:
            pass
    
    minute_list = sorted(minute_data.items(), reverse=True)[:60]  # Últimos 60 minutos
    stats["minute_data"] = [{"timestamp": k, **v} for k, v in minute_list]

    # Distribuição por hora (útil para análise de padrões diários)
    hourly_data = {}
    for p in processed:
        try:
            ts_str = p["timestamp"]
            if ts_str and ts_str != "—":
                hour_key = ts_str[:13]  # YYYY-MM-DD HH
                if hour_key not in hourly_data:
                    hourly_data[hour_key] = {"total": 0, "erros": 0, "enviados": 0, "entregues": 0, "lidos": 0, "respondidos": 0}
                hourly_data[hour_key]["total"] += 1
                if p["status_class"] == "error":
                    hourly_data[hour_key]["erros"] += 1
                elif p["status_class"] == "sent":
                    hourly_data[hour_key]["enviados"] += 1
                elif p["status_class"] == "delivered":
                    hourly_data[hour_key]["entregues"] += 1
                elif p["status_class"] == "read":
                    hourly_data[hour_key]["lidos"] += 1
                if p["status_class"] == "answered":
                    hourly_data[hour_key]["respondidos"] += 1
        except:
            pass
    
    hourly_list = sorted(hourly_data.items())
    stats["hourly_data"] = [{"timestamp": k, **v} for k, v in hourly_list]

    # Distribuição por dia (útil para análise de tendências)
    daily_data = {}
    for p in processed:
        try:
            ts_str = p["timestamp"]
            if ts_str and ts_str != "—":
                day_key = ts_str[:10]  # YYYY-MM-DD
                if day_key not in daily_data:
                    daily_data[day_key] = {"total": 0, "erros": 0, "enviados": 0, "entregues": 0, "lidos": 0, "respondidos": 0}
                daily_data[day_key]["total"] += 1
                if p["status_class"] == "error":
                    daily_data[day_key]["erros"] += 1
                elif p["status_class"] == "sent":
                    daily_data[day_key]["enviados"] += 1
                elif p["status_class"] == "delivered":
                    daily_data[day_key]["entregues"] += 1
                elif p["status_class"] == "read":
                    daily_data[day_key]["lidos"] += 1
                if p["status_class"] == "answered":
                    daily_data[day_key]["respondidos"] += 1
        except:
            pass
    
    daily_list = sorted(daily_data.items())
    stats["daily_data"] = [{"timestamp": k, **v} for k, v in daily_list]

    # Análise detalhada de erros por template
    error_analysis = {}
    for p in processed:
        if p["status_class"] == "error":
            template = p["template_name"]
            reason = p["reason"]
            
            if template not in error_analysis:
                error_analysis[template] = {"count": 0, "reasons": {}}
            
            error_analysis[template]["count"] += 1
            
            if reason not in error_analysis[template]["reasons"]:
                error_analysis[template]["reasons"][reason] = 0
            error_analysis[template]["reasons"][reason] += 1
    
    # Converter em lista ordenada por quantidade de erros
    error_list = []
    for template, data in error_analysis.items():
        error_list.append({
            "template": template,
            "total_errors": data["count"],
            "reasons": sorted([{"reason": r, "count": c} for r, c in data["reasons"].items()], 
                            key=lambda x: x["count"], reverse=True)
        })
    
    error_list.sort(key=lambda x: x["total_errors"], reverse=True)
    stats["error_analysis"] = error_list

    # Análise específica de erro 130429 (Rate Limit da Meta API)
    error_130429_count = sum(1 for p in processed if "130429" in str(p.get("reason", "")))
    stats["rate_limit_analysis"] = {
        "total_130429": error_130429_count,
        "capacity_used": error_130429_count,
        "capacity_remaining": max(0, 10 - error_130429_count),
        "capacity_limit": 10,
        "usage_percentage": round((error_130429_count / 10) * 100, 1)
    }

    total = len(processed)
    total_pages = max(1, -(-total // PAGE_SIZE))
    page = max(1, min(page, total_pages))
    start_idx = (page - 1) * PAGE_SIZE
    page_records = processed[start_idx:start_idx + PAGE_SIZE]

    return jsonify({
        "records": page_records,
        "templates": templates,
        "stats": stats,
        "pagination": {
            "page": page, "page_size": PAGE_SIZE, "total": total,
            "total_pages": total_pages,
            "has_prev": page > 1, "has_next": page < total_pages,
        },
        "rate_limit_hits": hits,
        "requests_last_minute": req_count,
        "api_rate_limit_count": api_rate_limit_count,
        "api_rate_limit_history": list(api_rate_limit_history),
        "alert": api_rate_limit_count > 10,
    })

@app.route("/api/hsm/rate-status")
def rate_status():
    now = time.time()
    while request_times and request_times[0] < now - 60:
        request_times.popleft()
    return jsonify({
        "requests_last_minute": len(request_times),
        "limit": RATE_LIMIT_PER_MINUTE,
        "rate_limit_hits": rate_limit_hits,
        "api_rate_limit_count": api_rate_limit_count,
        "api_rate_limit_history": list(api_rate_limit_history),
    })

@app.route("/api/hsm/export")
def export_csv():
    global rate_limit_hits
    start = request.args.get("startDate", datetime.now().strftime("%Y-%m-%d"))
    end = request.args.get("endDate", datetime.now().strftime("%Y-%m-%d"))
    template_filter = request.args.get("template", "")

    allowed, hits, req_count = check_rate_limit()
    if not allowed:
        return "Rate limit atingido. Aguarde.", 429

    try:
        url = f"{API_BASE}?origin={ORIGIN}&startDate={start}&endDate={end}"
        resp = requests.get(url, headers=HEADERS, timeout=240)

        if resp.status_code == 401:
            return "Não autorizado: token inválido.", 401
        if resp.status_code == 403:
            return "Acesso negado.", 403
        if resp.status_code == 404:
            return "Não encontrado.", 404
        if resp.status_code == 429:
            global api_rate_limit_count
            api_rate_limit_count += 1
            api_rate_limit_history.append({
                "timestamp": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
                "status_code": 429,
                "message": "Meta API Error: 130429 - (#130429) Rate limit hit"
            })
            return "Rate limit da API externa atingido.", 429
        if resp.status_code >= 500:
            return f"Erro no servidor da API ({resp.status_code}).", 500

        resp.raise_for_status()
        raw = resp.json()

    except requests.exceptions.Timeout:
        return "Tempo limite: API não respondeu.", 408
    except requests.exceptions.ConnectionError:
        return "Falha de conexão.", 503
    except Exception as e:
        return f"Erro: {str(e)}", 500

    all_records = raw if isinstance(raw, list) else raw.get("data", raw.get("records", [raw] if isinstance(raw, dict) else []))
    templates = sorted(set(r.get("template.name", "") for r in all_records if r.get("template.name")))

    if template_filter:
        all_records = [r for r in all_records if r.get("template.name") == template_filter]

    processed = []
    for r in all_records:
        st = r.get("status", "")
        processed.append({
            "timestamp": format_datetime(r.get("timestamp")),
            "key": r.get("key", "—"),
            "template_name": r.get("template.name", "—"),
            "status": translate_status(st),
            "status_class": status_class(st),
            "reason": r.get("reason", "—") or "—",
            "flow_id": r.get("parameters.flowId", "—") or "—",
            "agent_id": r.get("parameters.agentId", "—") or "—",
            "answer": r.get("parameters.answer", "—") or "—",
            "conversation_id": r.get("parameters.conversationId", "—") or "—",
        })

    # Gerar CSV
    import csv
    from io import StringIO
    si = StringIO()
    writer = csv.writer(si)
    writer.writerow(["Data/Hora", "Número", "Template", "Status", "Motivo", "ID Fluxo", "ID Agente", "ID Conversa"])
    for r in processed:
        writer.writerow([r["timestamp"], r["key"], r["template_name"], r["status"], r["reason"], r["flow_id"], r["agent_id"], r["conversation_id"]])
    output = si.getvalue()
    si.close()

    from flask import Response
    return Response(output, mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=relatorio_hsm.csv"})

@app.route("/api/rate-limit-history")
def rate_limit_history():
    return jsonify({
        "total": api_rate_limit_count,
        "history": list(api_rate_limit_history),
        "alert": api_rate_limit_count > 10,
    })

if __name__ == "__main__":
    app.run(debug=True, port=5050)
