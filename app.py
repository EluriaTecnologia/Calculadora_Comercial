import os
from datetime import datetime
from math import ceil
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
app.secret_key = os.getenv("SECRET_KEY", "change-me-in-production")

vercel_env = os.getenv("VERCEL_ENV") or os.getenv("VERCEL")

db_url = os.getenv("DATABASE_URL")
if not db_url:
    if vercel_env:
        db_path = os.path.join("/tmp", "local.db")
        db_url = f"sqlite:///{db_path}"
    else:
        db_url = "sqlite:///local.db"

app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class Lead(db.Model):
    __tablename__ = "leads"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(50), nullable=False)
    email = db.Column(db.String(120), nullable=False)
    company = db.Column(db.String(160), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def __repr__(self):
        return f"<Lead {self.id} - {self.name}>"

with app.app_context():
    db.create_all()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def br_money(v):
    """Formata moeda em pt-BR de forma simples (sem Babel)."""
    try:
        return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "R$ 0,00"

def parse_num(raw):
    """
    Converte string pt-BR para float:
    - remove separador de milhar (.)
    - troca vírgula decimal (,) por ponto (.)
    - retorna 0.0 se vazio/inválido
    """
    if raw is None:
        return 0.0
    s = str(raw).strip()
    if not s:
        return 0.0
    s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0

@app.context_processor
def inject_now():
    now = datetime.now()
    return {"now": now, "year": now.year, "br_money": br_money}

# ---------------------------------------------------------------------------
# Rotas
# ---------------------------------------------------------------------------

# Retrocompatibilidade: /login -> /
@app.route("/login")
def old_login():
    return redirect(url_for("capture"), code=301)

# Botão "Sair" do header (só redireciona, já que não há autenticação)
@app.route("/logout", methods=["POST"])
def logout():
    return redirect(url_for("capture"))

@app.route("/", methods=["GET", "POST"])
def capture():
    """
    Página de captura de dados (antiga 'login').
    Campos: Nome, Telefone, Email, Nome da Empresa.
    Ao enviar, salva no banco e redireciona para /dashboard?lead_id=...
    """
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        phone = (request.form.get("phone") or "").strip()
        email = (request.form.get("email") or "").strip()
        company = (request.form.get("company") or "").strip()

        errors = []
        if not name:
            errors.append("Informe o seu nome.")
        if not phone:
            errors.append("Informe o seu telefone.")
        if not email:
            errors.append("Informe o seu e-mail.")

        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("lead_capture.html")

        try:
            lead = Lead(name=name, phone=phone, email=email, company=company)
            db.session.add(lead)
            db.session.commit()
            flash("Dados recebidos com sucesso. Vamos iniciar sua análise comercial!", "success")
            return redirect(url_for("dashboard", lead_id=lead.id))
        except Exception:
            db.session.rollback()
            flash("Não foi possível salvar seus dados agora. Tente novamente em instantes.", "danger")
            return render_template("lead_capture.html")

    return render_template("lead_capture.html")

@app.route("/dashboard", methods=["GET", "POST"])
def dashboard():
    """
    Página da análise comercial.
    Se houver lead_id na querystring, mostra os dados do lead no topo.
    Renderiza 'resultados' como dicionário, conforme o template espera.
    """
    lead = None
    lead_id = request.args.get("lead_id", type=int)
    if lead_id:
        lead = Lead.query.get(lead_id)

    resultados = None  # importante p/ {% if resultados %} no template

    if request.method == "POST":
        # print("FORM:", request.form.to_dict())  # opcional para debug
        investimento = parse_num(request.form.get("investimento"))
        custo_lead = parse_num(request.form.get("custo_lead"))
        taxa_agendamento = parse_num(request.form.get("taxa_agendamento")) / 100.0
        taxa_comparecimento = parse_num(request.form.get("taxa_comparecimento")) / 100.0
        taxa_conversao = parse_num(request.form.get("taxa_conversao")) / 100.0
        ticket_medio = parse_num(request.form.get("ticket_medio"))

        leads = int(investimento / custo_lead) if custo_lead > 0 else 0
        agendamentos = int(leads * taxa_agendamento)
        comparecimentos = int(agendamentos * taxa_comparecimento)
        vendas = int(comparecimentos * taxa_conversao)
        receita = vendas * ticket_medio
        cac = (investimento / vendas) if vendas > 0 else 0.0
        roas = (receita / investimento) if investimento > 0 else 0.0
        custo_por_call = (investimento / comparecimentos) if comparecimentos > 0 else 0.0

        sdrs = max(1, ceil(comparecimentos / 180))  # capacidade de 180 por mês
        closers = max(1, ceil(vendas / 120))        # capacidade de 120 por mês

        taxa_total_funil = round(((vendas / leads) * 100), 2) if leads > 0 else 0.0
        retorno_por_lead = round((receita / leads), 2) if leads > 0 else 0.0
        lucro = receita - investimento

        # >>> AQUI empacotamos no dict que o template usa <<<
        resultados = {
            "leads": leads,
            "agendamentos": agendamentos,
            "comparecimentos": comparecimentos,
            "vendas": vendas,
            "receita": round(receita, 2),
            "roas": round(roas, 2),
            "cac": round(cac, 2),
            "custo_por_call": round(custo_por_call, 2),
            "sdrs": sdrs,
            "closers": closers,
            "taxa_total_funil": taxa_total_funil,
            "retorno_por_lead": round(retorno_por_lead, 2),
            "lucro": round(lucro, 2),
        }

    return render_template("dashboard.html", lead=lead, resultados=resultados, year=datetime.now().year)

# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Em produção, usar um WSGI server (gunicorn/uwsgi) e DEBUG=False
    app.run(debug=True)
