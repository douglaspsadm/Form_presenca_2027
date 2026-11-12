# ✅ Lista de Presença — XI ENCES (Supabase)

Sistema de registro de presença com verificação por geolocalização (GPS), controle de turnos e banco de dados PostgreSQL via **Supabase**.

---

## 🚀 Passo a Passo para Configurar o Supabase

### 1. Criar as Tabelas no Supabase
1. Acesse o painel do seu projeto no [Supabase Dashboard](https://supabase.com/dashboard).
2. No menu lateral esquerdo, clique em **SQL Editor** → **New query**.
3. Copie todo o conteúdo do arquivo [`setup_supabase.sql`](./setup_supabase.sql), cole no editor e clique em **Run**.

Isso criará automaticamente:
- **`lista_evento`**: Tabela com os participantes inscritos (`co_ies`, `no_ies`, `no_pessoa_fisica`).
- **`presencas`**: Tabela onde as presenças são registradas sem risco de conflito simultâneo.
- **`historico_logs`**: Tabela de backup/auditoria de cada registro.

---

### 2. Importar a Lista de Participantes (`lista_evento`)
1. No menu lateral do Supabase, clique em **Table Editor** → selecione a tabela **`lista_evento`**.
2. Clique no botão **Insert** → **Import data from CSV**.
3. Envie o arquivo CSV da sua planilha `lista_evento` contendo as colunas:
   - `co_ies` (Código da IES)
   - `no_ies` (Nome da IES)
   - `no_pessoa_fisica` (Nome completo do participante)

---

### 3. Configurar as Credenciais no Streamlit Cloud
Quando publicar o app no [Streamlit Community Cloud](https://share.streamlit.io/), vá em **App Settings** → **Secrets** e adicione as credenciais do seu projeto (disponíveis em *Project Settings > API* no Supabase):

```toml
SUPABASE_URL = "https://seu-projeto.supabase.co"
SUPABASE_KEY = "sua-chave-publica-supabase"
```

---

### 4. Exportar os Dados de Presença (Excel / CSV)
Para baixar a lista de presença a qualquer momento:
1. Acesse **Table Editor** no painel do Supabase.
2. Clique na tabela **`presencas`**.
3. Clique no botão **Export** → **Export as CSV**.
