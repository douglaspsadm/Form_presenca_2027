import math
import time
from datetime import datetime
import pandas as pd
import pytz
import streamlit as st
from supabase import create_client, Client

# ══════════════════════════════════════════════════════════════════
# CONFIGURAÇÕES GERAIS
# ══════════════════════════════════════════════════════════════════

st.set_page_config(page_title="Lista de Presença - XI ENCES", page_icon="✅")

# Fuso horário do evento
FUSO = pytz.timezone("America/Sao_Paulo")

EVENTO_LAT = -15.78798   # ← latitude do local do evento
EVENTO_LON = -47.91416   # ← longitude do local do evento
RAIO_MAXIMO_METROS = 4000  # raio em metros (300m é bem preciso para um prédio)

TURNOS = {
    "presenca_dia1_manha": {
        "label":  "📅 Dia 1 — Manhã",
        "inicio": datetime(2026, 11, 12,  7,  00, tzinfo=FUSO),
        "fim":    datetime(2026, 11, 12, 12, 00, tzinfo=FUSO),
    },
    "presenca_dia1_tarde": {
        "label":  "📅 Dia 1 — Tarde",
        "inicio": datetime(2026, 11, 12, 13, 30, tzinfo=FUSO),
        "fim":    datetime(2026, 11, 12, 18, 30, tzinfo=FUSO),
    },
    "presenca_dia2_manha": {
        "label":  "📅 Dia 2 — Manhã",
        "inicio": datetime(2026, 11, 12,  7,  00, tzinfo=FUSO),
        "fim":    datetime(2026, 11, 12, 13, 00, tzinfo=FUSO),
    },
    "presenca_dia2_tarde": {
        "label":  "📅 Dia 2 — Tarde",
        "inicio": datetime(2026, 11, 12, 13, 10, tzinfo=FUSO),
        "fim":    datetime(2026, 11, 12, 18, 30, tzinfo=FUSO),
    },
}

COLUNAS_PRESENCA = list(TURNOS.keys())
TODAS_COLUNAS    = ["nome_participante", "nome_ies"] + COLUNAS_PRESENCA


# ══════════════════════════════════════════════════════════════════
# CONEXÃO COM O SUPABASE
# ══════════════════════════════════════════════════════════════════

@st.cache_resource
def get_supabase() -> Client:
    """Inicializa e mantém a conexão com o Supabase."""
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)


# ══════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════

def timestamp_agora() -> str:
    """Retorna data e hora atual formatada."""
    return datetime.now(FUSO).strftime("%d-%m-%Y %Hh%M")


def celula_preenchida(valor) -> bool:
    """True se o campo possui um valor válido preenchido."""
    if valor is None:
        return False
    return pd.notna(valor) and str(valor).strip() not in ("", "nan", "NaN", "None")


# ══════════════════════════════════════════════════════════════════
# LEITURA E ESCRITA NO SUPABASE
# ══════════════════════════════════════════════════════════════════

@st.cache_data(ttl=60)
def carregar_lista_evento() -> pd.DataFrame:
    """
    Carrega a lista de participantes e IES do Supabase.
    Busca em lotes caso haja mais de 1000 inscritos.
    """
    supabase = get_supabase()
    todos_registros = []
    offset = 0
    limite = 1000

    while True:
        res = (
            supabase.table("lista_evento")
            .select("co_ies, no_ies, no_pessoa_fisica")
            .range(offset, offset + limite - 1)
            .execute()
        )
        dados = res.data or []
        todos_registros.extend(dados)
        if len(dados) < limite:
            break
        offset += limite

    if not todos_registros:
        return pd.DataFrame(columns=["co_ies", "no_ies", "no_pessoa_fisica"])

    return pd.DataFrame(todos_registros)


def buscar_registro_participante(participante: str) -> dict | None:
    """Busca o registro de presença de um participante específico direto no banco."""
    supabase = get_supabase()
    res = (
        supabase.table("presencas")
        .select("*")
        .eq("nome_participante", participante)
        .limit(1)
        .execute()
    )
    if res.data:
        return res.data[0]
    return None


def registrar_log_backup(ies: str, participante: str, turno_col: str, horario: str):
    """Salva um registro individual na tabela de log/backup (não interrompe se falhar)."""
    try:
        supabase = get_supabase()
        supabase.table("historico_logs").insert({
            "nome_participante": participante,
            "nome_ies": ies,
            "turno": turno_col,
            "registrado_em": horario,
        }).execute()
    except Exception:
        pass


def adicionar_presenca(ies: str, participante: str, turno_col: str) -> bool:
    """
    Registra a presença diretamente no PostgreSQL (Supabase).
    Diferente do Google Sheets, operações aqui são transacionais por linha,
    eliminando o risco de um participante sobrescrever a planilha de outro.
    """
    try:
        supabase = get_supabase()
        agora = timestamp_agora()

        registro_atual = buscar_registro_participante(participante)

        # Verifica se já tem presença neste turno
        if registro_atual and celula_preenchida(registro_atual.get(turno_col)):
            return False

        if registro_atual:
            # UPDATE apenas na coluna do turno atual para este participante
            supabase.table("presencas").update({
                turno_col: agora,
                "updated_at": datetime.now(FUSO).isoformat(),
            }).eq("nome_participante", participante).execute()
        else:
            # INSERT de novo participante (ou UPSERT caso haja clique duplo no mesmo milissegundo)
            novo_registro = {
                "nome_participante": participante,
                "nome_ies": ies,
                turno_col: agora,
            }
            supabase.table("presencas").upsert(
                novo_registro,
                on_conflict="nome_participante"
            ).execute()

        # Registra log de auditoria
        registrar_log_backup(ies, participante, turno_col, agora)
        return True

    except Exception as exc:
        st.error(f"❌ Erro ao salvar presença no banco de dados: {exc}")
        return False


# ══════════════════════════════════════════════════════════════════
# GEOLOCALIZAÇÃO
# ══════════════════════════════════════════════════════════════════

def calcular_distancia_metros(lat1, lon1, lat2, lon2) -> int:
    R       = 6_371_000
    phi1    = math.radians(lat1)
    phi2    = math.radians(lat2)
    dphi    = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (math.sin(dphi / 2) ** 2
         + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2)
    return round(2 * R * math.asin(math.sqrt(a)))


def verificar_dentro_do_evento(lat, lon):
    distancia = calcular_distancia_metros(lat, lon, EVENTO_LAT, EVENTO_LON)
    return distancia <= RAIO_MAXIMO_METROS, distancia


def obter_localizacao():
    try:
        from streamlit_js_eval import get_geolocation
        return get_geolocation()
    except ImportError:
        st.error("❌ Pacote não encontrado. Execute: pip install streamlit-js-eval")
        return None


# ══════════════════════════════════════════════════════════════════
# TURNO ATIVO
# ══════════════════════════════════════════════════════════════════

def get_turno_ativo():
    agora = datetime.now(FUSO)
    for chave, turno in TURNOS.items():
        if turno["inicio"] <= agora <= turno["fim"]:
            return chave, turno["label"]
    return None, None


# ══════════════════════════════════════════════════════════════════
# HELPERS DE PARTICIPANTES
# ══════════════════════════════════════════════════════════════════

def get_iniciais(nome):
    return ' '.join(palavra[0].upper() for palavra in str(nome).split() if palavra)


def get_ies_list():
    lista_evento = carregar_lista_evento()
    if lista_evento.empty:
        return []
    lista_evento = lista_evento.copy()
    lista_evento['ies_completo'] = (
        lista_evento['co_ies'].astype(int).astype(str) + ' - ' + lista_evento['no_ies'].astype(str)
    )
    return sorted(lista_evento['ies_completo'].unique())


def get_participantes_ies(ies_selecionada):
    lista_evento = carregar_lista_evento()
    if lista_evento.empty:
        return []

    co_ies = int(ies_selecionada.split(' - ')[0])
    participantes = lista_evento[
        lista_evento['co_ies'].astype(int) == co_ies
    ]['no_pessoa_fisica'].tolist()

    if 'mapeamento_nomes' not in st.session_state:
        st.session_state.mapeamento_nomes = {}

    participantes_iniciais = []
    for nome in participantes:
        iniciais      = get_iniciais(nome)
        base_iniciais = iniciais
        contador      = 1
        while (iniciais in st.session_state.mapeamento_nomes
               and st.session_state.mapeamento_nomes[iniciais] != nome):
            iniciais = f"{base_iniciais} ({contador})"
            contador += 1
        st.session_state.mapeamento_nomes[iniciais] = nome
        participantes_iniciais.append(iniciais)

    return participantes_iniciais


def verificar_presenca_existente(participante, turno_col) -> bool:
    registro = buscar_registro_participante(participante)
    if not registro:
        return False
    return celula_preenchida(registro.get(turno_col))


def mostrar_historico(participante):
    registro = buscar_registro_participante(participante)
    if not registro:
        return
    st.markdown("**Seu histórico de presenças:**")
    for col in COLUNAS_PRESENCA:
        valor = registro.get(col, "") or ""
        icone = "✅" if celula_preenchida(valor) else "⬜"
        label = valor if celula_preenchida(valor) else "—"
        st.write(f"{icone} {TURNOS[col]['label']}: {label}")


# ══════════════════════════════════════════════════════════════════
# INTERFACE PRINCIPAL
# ══════════════════════════════════════════════════════════════════

def main():
    st.title("✅ Lista de Presença — XI ENCES")

    # Flag de proteção contra duplo clique
    if "registrando" not in st.session_state:
        st.session_state.registrando = False

    # ── PASSO 1: Turno ativo ──────────────────────────────────────
    turno_col, turno_label = get_turno_ativo()

    if not turno_col:
        st.warning("⏰ **Nenhum turno de presença está aberto no momento.**")
        st.markdown("#### Horários de registro:")
        for _, t in TURNOS.items():
            st.write(
                f"• **{t['label']}**: "
                f"{t['inicio'].strftime('%d/%m às %H:%M')} — "
                f"{t['fim'].strftime('%H:%M')}h"
            )
        return

    st.success(f"🟢 Turno aberto: **{turno_label}**")
    st.divider()

    # ── PASSO 2: Geolocalização ───────────────────────────────────
    st.markdown("### 📍 Verificação de localização")
    st.caption(
        f"O registro só é permitido a até **{RAIO_MAXIMO_METROS}m** do local do evento. "
        "Permita o acesso à sua localização quando solicitado."
    )

    loc = obter_localizacao()

    if loc is None:
        st.info("⏳ Aguardando permissão de localização...")
        return

    lat = loc.get("coords", {}).get("latitude")
    lon = loc.get("coords", {}).get("longitude")

    if lat is None or lon is None:
        st.error("❌ Não foi possível obter sua localização. Verifique se o GPS está ativo.")
        return

    dentro, distancia = verificar_dentro_do_evento(lat, lon)

    if not dentro:
        st.error(
            f"🚫 Você está a **{distancia}m** do evento. "
            f"O registro só é permitido a até {RAIO_MAXIMO_METROS}m."
        )
        return

    st.success(f"✅ Localização confirmada! Você está a **{distancia}m** do evento.")
    st.divider()

    # ── PASSO 3: IES ──────────────────────────────────────────────
    ies_lista = get_ies_list()
    if not ies_lista:
        st.warning("⚠️ Nenhuma instituição encontrada na tabela `lista_evento` do Supabase.")
        return

    ies_options = ["Selecione uma IES..."] + list(ies_lista)
    ies = st.selectbox("Selecione sua Instituição", options=ies_options)

    if ies == "Selecione uma IES...":
        return

    # ── PASSO 4: Participante ─────────────────────────────────────
    participantes_iniciais = get_participantes_ies(ies)

    if not participantes_iniciais:
        st.error("Nenhum participante encontrado para esta IES")
        return

    participante_iniciais = st.selectbox(
        "Selecione o Participante",
        options=["Selecione um participante..."] + participantes_iniciais
    )

    if participante_iniciais == "Selecione um participante...":
        return

    nome_completo = st.session_state.mapeamento_nomes[participante_iniciais]

    # ── PASSO 5: Verifica presença duplicada ──────────────────────
    if verificar_presenca_existente(nome_completo, turno_col):
        st.warning(
            f"⚠️ **{participante_iniciais}** já registrou presença para **{turno_label}**.\n\n"
            "Não é permitido registrar presença mais de uma vez no mesmo turno."
        )
        mostrar_historico(nome_completo)
        return

    # ── PASSO 6: Confirmar ────────────────────────────────────────
    st.divider()
    st.markdown("### 📋 Confirmação de Presença")

    col1, col2 = st.columns(2)
    with col1:
        st.markdown(f"**Participante:** {participante_iniciais}")
        st.markdown(f"**IES:** {ies}")
    with col2:
        st.markdown(f"**Turno:** {turno_label}")
        st.markdown(f"**Localização:** ✅ {distancia}m do evento")

    st.markdown("")

    submitted = st.button(
        "✅ Confirmar Presença",
        type="primary",
        use_container_width=True,
        disabled=st.session_state.registrando
    )

    if submitted and not st.session_state.registrando:
        st.session_state.registrando = True

        # Verificação dupla antes de gravar
        if verificar_presenca_existente(nome_completo, turno_col):
            st.warning("⚠️ Presença já registrada para este turno.")
            mostrar_historico(nome_completo)
            st.session_state.registrando = False
            return

        with st.spinner("Registrando presença..."):
            sucesso = adicionar_presenca(ies, nome_completo, turno_col)

        st.session_state.registrando = False

        if sucesso:
            st.success("🎉 **Presença registrada com sucesso!**")
            st.balloons()
            time.sleep(2)
            st.rerun()
        else:
            st.error("Não foi possível registrar a presença. Por favor, tente novamente.")


if __name__ == "__main__":
    main()
