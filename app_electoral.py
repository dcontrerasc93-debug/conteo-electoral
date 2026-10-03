import streamlit as st
import pandas as pd
import sqlite3
from openai import OpenAI
import json
import base64
from datetime import datetime

# Configuración de la página
st.set_page_config(
    page_title="Sistema Electoral Regional y Municipal",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- 1. BASE DE DATOS CENTRALIZADA (SQLite) ---
def init_db():
    conn = sqlite3.connect("votos_electorales_multiples.db")
    c = conn.cursor()
    # Tabla de actas/carteles
    c.execute('''
        CREATE TABLE IF NOT EXISTS actas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            clave_unica TEXT UNIQUE,
            mesa TEXT,
            tipo_eleccion TEXT,
            departamento TEXT,
            provincia TEXT,
            distrito TEXT,
            votos_blanco INTEGER,
            votos_nulos INTEGER,
            votos_impugnados INTEGER,
            total_emitidos INTEGER,
            usuario TEXT,
            fecha_registro TEXT
        )
    ''')
    # Tabla de detalles de votos por partido
    c.execute('''
        CREATE TABLE IF NOT EXISTS votos_partido (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            clave_unica TEXT,
            mesa TEXT,
            tipo_eleccion TEXT,
            partido TEXT,
            votos INTEGER,
            FOREIGN KEY (clave_unica) REFERENCES actas (clave_unica)
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# --- 2. FUNCIONES DE BASE DE DATOS ---
def guardar_acta(data, tipo_eleccion_manual, usuario):
    conn = sqlite3.connect("votos_electorales_multiples.db")
    c = conn.cursor()
    
    mesa = str(data.get("mesa", "000000")).strip()
    tipo_eleccion = tipo_eleccion_manual if tipo_eleccion_manual != "Automático (Detectar por IA)" else data.get("tipo_eleccion", "PRESIDENTE REGIONAL").upper().strip()
    
    # Clave única: combinación de N° de Mesa + Tipo de Elección
    # Permite registrar la mesa 077040 para Alcalde Provincial y para Gobernador, pero no duplicar la misma elección
    clave_unica = f"{mesa}_{tipo_eleccion}"
    
    c.execute("SELECT clave_unica FROM actas WHERE clave_unica = ?", (clave_unica,))
    if c.fetchone():
        conn.close()
        return False, f"⚠️ La foto para la Mesa N° {mesa} ({tipo_eleccion}) ya fue ingresada previamente."

    fecha_actual = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute('''
        INSERT INTO actas (clave_unica, mesa, tipo_eleccion, departamento, provincia, distrito, votos_blanco, votos_nulos, votos_impugnados, total_emitidos, usuario, fecha_registro)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        clave_unica,
        mesa,
        tipo_eleccion,
        data.get("departamento", ""),
        data.get("provincia", ""),
        data.get("distrito", ""),
        int(data.get("votos_blanco", 0)),
        int(data.get("votos_nulos", 0)),
        int(data.get("votos_impugnados", 0)),
        int(data.get("total_emitidos", 0)),
        usuario,
        fecha_actual
    ))

    # Insertar votos por partido
    for item in data.get("resultados", []):
        partido_nombre = str(item.get("partido", "")).strip().upper()
        cant_votos = int(item.get("votos", 0))
        c.execute('''
            INSERT INTO votos_partido (clave_unica, mesa, tipo_eleccion, partido, votos)
            VALUES (?, ?, ?, ?, ?)
        ''', (clave_unica, mesa, tipo_eleccion, partido_nombre, cant_votos))

    conn.commit()
    conn.close()
    return True, f"✅ Mesa N° {mesa} ({tipo_eleccion}) registrada exitosamente."

def obtener_sumatoria_por_eleccion(tipo_eleccion):
    conn = sqlite3.connect("votos_electorales_multiples.db")
    
    query_partidos = '''
        SELECT partido AS "Partido / Agrupación", SUM(votos) AS "Total Votos"
        FROM votos_partido
        WHERE tipo_eleccion = ?
        GROUP BY partido
    '''
    df_partidos = pd.read_sql_query(query_partidos, conn, params=(tipo_eleccion,))

    query_otros = '''
        SELECT 
            SUM(votos_blanco) as "VOTOS EN BLANCO",
            SUM(votos_nulos) as "VOTOS NULOS",
            SUM(votos_impugnados) as "VOTOS IMPUGNADOS"
        FROM actas
        WHERE tipo_eleccion = ?
    '''
    df_otros = pd.read_sql_query(query_otros, conn, params=(tipo_eleccion,))
    conn.close()

    if not df_otros.empty and df_otros["VOTOS EN BLANCO"].iloc[0] is not None:
        blancos = df_otros["VOTOS EN BLANCO"].iloc[0] or 0
        nulos = df_otros["VOTOS NULOS"].iloc[0] or 0
        impugnados = df_otros["VOTOS IMPUGNADOS"].iloc[0] or 0

        df_extra = pd.DataFrame([
            {"Partido / Agrupación": "VOTOS EN BLANCO", "Total Votos": blancos},
            {"Partido / Agrupación": "VOTOS NULOS", "Total Votos": nulos},
            {"Partido / Agrupación": "VOTOS IMPUGNADOS", "Total Votos": impugnados}
        ])
        df_partidos = pd.concat([df_partidos, df_extra], ignore_index=True)

    if not df_partidos.empty:
        df_partidos = df_partidos.sort_values(by="Total Votos", ascending=False).reset_index(drop=True)
    
    return df_partidos

def obtener_resumen_actas():
    conn = sqlite3.connect("votos_electorales_multiples.db")
    df_actas = pd.read_sql_query("SELECT mesa AS 'Mesa', tipo_eleccion AS 'Elección', departamento AS 'Dpto', provincia AS 'Provincia', distrito AS 'Distrito', total_emitidos AS 'Emitidos', usuario AS 'Personero', fecha_registro AS 'Fecha/Hora' FROM actas ORDER BY id DESC", conn)
    conn.close()
    return df_actas


# --- 3. MENÚ PRINCIPAL ---
st.sidebar.title("🗳️ Centro Electoral Regional")
rol = st.sidebar.radio("Navegación:", ["📱 Enviar Foto (Personero)", "📊 Tablero Central de Cómputo"])
api_key = st.sidebar.text_input("OpenAI API Key:", type="password")


# ==========================================
# MÓDULO 1: PERSONEROS (ENVÍO DE FOTOS)
# ==========================================
if rol == "📱 Enviar Foto (Personero)":
    st.header("📱 Reporte de Mesa por Elección")
    st.write("Suba la foto del cartel de resultados y seleccione el tipo de elección correspondientes.")

    col1, col2 = st.columns(2)
    with col1:
        nombre_personero = st.text_input("Nombre / Código del Personero:", value="Personero_1")
    with col2:
        tipo_eleccion_input = st.selectbox(
            "Tipo de Elección del Cartel:",
            [
                "Automático (Detectar por IA)",
                "PRESIDENTE / GOBERNADOR REGIONAL",
                "CONSEJERO REGIONAL",
                "ALCALDE PROVINCIAL",
                "ALCALDE DISTRITAL"
            ]
        )

    foto = st.file_uploader("Capturar / Subir Foto del Cartel", type=["jpg", "jpeg", "png"])

    if foto and api_key:
        if st.button("🚀 Procesar e Ingresar a Base de Datos Central", type="primary"):
            client = OpenAI(api_key=api_key)
            bytes_data = foto.read()
            base64_image = base64.b64encode(bytes_data).decode('utf-8')

            prompt = """
            Analiza este cartel de resultados de elecciones.
            1. Determina el TIPO DE ELECCIÓN entre: "PRESIDENTE / GOBERNADOR REGIONAL", "CONSEJERO REGIONAL", "ALCALDE PROVINCIAL", "ALCALDE DISTRITAL".
            2. Extrae el número de mesa, departamento, provincia, distrito.
            3. Extrae la lista completa de partidos o movimientos políticos con sus votos manuscritos.

            Devuelve ÚNICAMENTE este JSON:
            {
              "tipo_eleccion": "ALCALDE PROVINCIAL",
              "mesa": "077040",
              "departamento": "PUNO",
              "provincia": "EL COLLAO",
              "distrito": "ILAVE",
              "resultados": [
                {"partido": "MOVIMIENTO REGIONAL A", "votos": 45}
              ],
              "votos_blanco": 10,
              "votos_nulos": 5,
              "votos_impugnados": 0,
              "total_emitidos": 230
            }
            """

            with st.spinner("Procesando la foto y extrayendo los conteos con IA..."):
                try:
                    response = client.chat.completions.create(
                        model="gpt-4o",
                        response_format={"type": "json_object"},
                        messages=[
                            {
                                "role": "user",
                                "content": [
                                    {"type": "text", "text": prompt},
                                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                                ]
                            }
                        ],
                        max_tokens=2500
                    )

                    data = json.loads(response.choices[0].message.content)
                    
                    exito, msj = guardar_acta(data, tipo_eleccion_input, nombre_personero)

                    if exito:
                        st.success(msj)
                        st.json(data)
                    else:
                        st.error(msj)

                except Exception as e:
                    st.error(f"Error procesando la imagen: {e}")

    elif foto and not api_key:
        st.warning("Ingrese su API Key en la barra lateral para continuar.")

# ==========================================
# MÓDULO 2: TABLERO CENTRAL (CÓMPUTO GENERAL)
# ==========================================
elif rol == "📊 Tablero Central de Cómputo":
    st.header("📊 Centro de Cómputo General y Conteos Consolidados")
    
    if st.button("🔄 Actualizar Datos en Vivo"):
        st.rerun()

    df_actas = obtener_resumen_actas()
    st.metric("Total Carteles Procesados (Todas las Elecciones)", len(df_actas))

    st.divider()

    # Pestañas ordenadas para cada elección
    tab1, tab2, tab3, tab4 = st.tabs([
        "🏛️ Gobernador Regional", 
        "👔 Consejero Regional", 
        "🏙️ Alcalde Provincial", 
        "🏘️ Alcalde Distrital"
    ])

    elecciones_map = [
        (tab1, "PRESIDENTE / GOBERNADOR REGIONAL"),
        (tab2, "CONSEJERO REGIONAL"),
        (tab3, "ALCALDE PROVINCIAL"),
        (tab4, "ALCALDE DISTRITAL")
    ]

    for tab, nombre_eleccion in elecciones_map:
        with tab:
            st.subheader(f"Resultados Consolidados: {nombre_eleccion}")
            df_totales = obtener_sumatoria_por_eleccion(nombre_eleccion)

            if not df_totales.empty:
                c1, c2 = st.columns([1, 1])
                with c1:
                    st.dataframe(df_totales, use_container_width=True, height=400)
                    csv = df_totales.to_csv(index=False).encode('utf-8')
                    st.download_button(
                        label=f"📥 Descargar CSV ({nombre_eleccion})",
                        data=csv,
                        file_name=f"votos_{nombre_eleccion.lower().replace(' ', '_')}.csv",
                        mime="text/csv"
                    )
                with c2:
                    st.bar_chart(df_totales.set_index("Partido / Agrupación"), y="Total Votos", color="#2A9D8F")
            else:
                st.info(f"Aún no hay votos registrados para {nombre_eleccion}.")

    st.divider()
    st.subheader("📋 Lista General de Mesas y Elecciones Registradas")
    st.dataframe(df_actas, use_container_width=True)