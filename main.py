from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from supabase import create_client, Client
from datetime import datetime

# ==========================================
# INICIALIZAÇÃO DO FASTAPI E SUPABASE
# ==========================================
app = FastAPI()

URL = "https://cbrwmscaidyeaamyfiyt.supabase.co"
KEY = "sb_publishable_neiGbVa2X1nBfX5wT3UGYw_3RWe43_G"
supabase: Client = create_client(URL, KEY)

# ==========================================
# LIBERAÇÃO DE CORS (Para o Live Server conseguir falar com o Python)
# ==========================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================================
# ROTA DE LOGIN
# ==========================================
class LoginData(BaseModel):
    usuario: str
    senha: str

@app.post("/api/login")
def api_login(dados: LoginData):
    resposta = supabase.table("usuarios").select("*").eq("login", dados.usuario).eq("senha", dados.senha).execute()
    
    if resposta.data and len(resposta.data) > 0:
        return {"sucesso": True, "usuario": resposta.data[0]}
    else:
        raise HTTPException(status_code=401, detail="Usuário ou senha incorretos.")

# ==========================================
# ROTAS DO MÓDULO CONTAGEM P.A. (COLETOR)
# ==========================================
class Contagem(BaseModel):
    nItem: str
    desc: str
    moove: str
    pax: str
    lote: str
    dataFab: str
    qtd: float

@app.get("/api/buscar-produto-pa")
def api_buscar_produto_pa(termo: str):
    termo_limpo = ''.join(filter(str.isdigit, termo))
    
    if not termo_limpo:
        return []

    resposta = supabase.table("produtos_moove").select("*").or_(f"n_item.ilike.%{termo_limpo}%,cod_moove.ilike.%{termo_limpo}%,cod_pax.ilike.%{termo_limpo}%").execute()
    
    resultados = []
    for d in resposta.data:
        resultados.append({
            "nItem": d.get("n_item", "N/A"),
            "desc": d.get("descricao", "N/A"),
            "moove": d.get("cod_moove", "N/A"),
            "pax": d.get("cod_pax", "N/A"),
            "qtdePalete": d.get("qtd_palete", "N/D"),
            "peso": d.get("peso", 0),
            "cliente": d.get("cliente", "S/ CLIENTE")
        })
    return resultados

@app.get("/api/verificar-lote")
def api_verificar_lote(nItem: str, lote: str):
    resposta = supabase.table("inventario_pa").select("data_fabricacao").eq("n_item", nItem).eq("lote", lote.upper()).order("id", desc=True).limit(1).execute()
    
    if resposta.data and resposta.data[0].get("data_fabricacao"):
        return {"data": resposta.data[0]["data_fabricacao"]}
    return {"data": None}

@app.post("/api/salvar-contagem")
def api_salvar_contagem(dados: Contagem):
    hoje = datetime.now().strftime("%Y-%m-%d")
    
    busca_hoje = supabase.table("inventario_pa").select("id, qtd_fisica").eq("data_inventario", hoje).eq("n_item", dados.nItem).eq("lote", dados.lote.upper()).execute()
    
    if busca_hoje.data:
        id_registro = busca_hoje.data[0]["id"]
        qtd_atual = float(busca_hoje.data[0]["qtd_fisica"])
        nova_qtd = qtd_atual + dados.qtd
        
        supabase.table("inventario_pa").update({"qtd_fisica": nova_qtd}).eq("id", id_registro).execute()
        return {"sucesso": True, "mensagem": "Quantidade somada ao lote existente!"}
    
    else:
        novo_registro = {
            "data_inventario": hoje,
            "n_item": dados.nItem,
            "lote": dados.lote.upper(),
            "data_fabricacao": dados.dataFab,
            "qtd_fisica": dados.qtd
        }
        supabase.table("inventario_pa").insert(novo_registro).execute()
        
        supabase.table("produtos_moove").upsert({
            "n_item": dados.nItem,
            "descricao": dados.desc,
            "cod_moove": dados.moove,
            "cod_pax": dados.pax
        }, on_conflict="n_item").execute()
        
        return {"sucesso": True, "mensagem": "Nova contagem registrada com sucesso!"}

# ==========================================
# ROTAS DO MÓDULO CONTROLADORIA
# ==========================================
class AcaoControladoria(BaseModel):
    nItem: str
    lote: str
    tipoAcao: str
    valorAcao: str

@app.get("/api/dados-controladoria")
def api_dados_controladoria(data: str):
    inv_res = supabase.table("inventario_pa").select("n_item, lote, data_fabricacao, qtd_fisica, produtos_moove(descricao)").eq("data_inventario", data).execute()
    
    if not inv_res.data:
        return {"registros": []}

    agrupado = {}
    for row in inv_res.data:
        n_item = row["n_item"]
        lote = row["lote"]
        chave = f"{n_item}_{lote}"
        
        if chave not in agrupado:
            agrupado[chave] = {
                "nItem": n_item,
                "desc": row["produtos_moove"]["descricao"] if row.get("produtos_moove") else "N/A",
                "lote": lote,
                "dataFab": row["data_fabricacao"],
                "qtdTotal": 0,
                "dataOp": "",
                "statusExpedicao": "AGUARDANDO"
            }
        agrupado[chave]["qtdTotal"] += float(row["qtd_fisica"])

    ctrl_res = supabase.table("controle_op").select("*").execute()
    mapa_ctrl = {f"{c['n_item']}_{c['lote']}": c for c in ctrl_res.data}

    registros = []
    for chave, item in agrupado.items():
        if chave in mapa_ctrl:
            info = mapa_ctrl[chave]
            if info.get("data_op"):
                try:
                    data_obj = datetime.fromisoformat(info["data_op"].replace('Z', '+00:00'))
                    item["dataOp"] = data_obj.strftime("%d/%m/%Y %H:%M")
                except:
                    item["dataOp"] = info["data_op"]
            item["statusExpedicao"] = info.get("status_expedicao", "AGUARDANDO")
        
        registros.append(item)

    registros.sort(key=lambda x: (x["dataOp"] != "", x["nItem"]))
    return {"registros": registros}

@app.post("/api/atualizar-controladoria")
def api_atualizar_controladoria(acao: AcaoControladoria):
    agora = datetime.now().isoformat()
    
    dados_update = {"data_atualizacao": agora}
    
    if acao.tipoAcao == 'OP':
        dados_update["data_op"] = agora
    elif acao.tipoAcao == 'EXPEDICAO':
        dados_update["status_expedicao"] = acao.valorAcao.upper()

    dados_insert = {
        "n_item": acao.nItem,
        "lote": acao.lote,
        "data_atualizacao": agora
    }
    
    dados_final = {**dados_insert, **dados_update}

    resposta = supabase.table("controle_op").upsert(dados_final).execute()
    
    if resposta.data:
        return {"sucesso": True, "mensagem": "Status atualizado com sucesso!"}
    
    raise HTTPException(status_code=400, detail="Falha ao atualizar no banco.")