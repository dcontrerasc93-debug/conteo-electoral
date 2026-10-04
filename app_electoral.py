import streamlit as st
import sqlite3
import pandas as pd

# --- CONEXIÓN A LA BASE DE DATOS ---
conn = sqlite3.connect('votos_electorales_v2.db', check_same_thread=False)
c = conn.cursor()

# Crear tabla por si es la primera vez
c.execute('''
    CREATE TABLE IF NOT EXISTS actas (
        numero_mesa TEXT PRIMARY KEY,
        votos_partido_1 INTEGER,
        votos_partido_2 INTEGER,
        votos_blancos INTEGER,
        votos_nulos INTEGER,
        fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
''')
conn.commit()

# --- INTERFAZ PRINCIPAL ---
st.title("🗳️ Sistema de Conteo Electoral en Vivo")

tab1, tab2 = st.tabs(["📊 Suma Total General", "🔍 Consulta por Número de Mesa"])

# Cargar datos existentes
df = pd.read_sql_query("SELECT * FROM actas", conn)

# ---------------------------------------------------------
# PESTAÑA 1: SUMA TOTAL GENERAL
# ---------------------------------------------------------
with tab1:
    st.header("Resultados Consolidados")
    
    if not df.empty:
        # Detectar columnas numéricas automáticamente para evitar KeyErrors
        columnas_numericas = df.select_dtypes(include=['number', 'int64', 'float64']).columns.tolist()
        
        if columnas_numericas:
            st.subheader("Totales Acumulados")
            
            # Crear métricas dinámicas para cada columna con votos
            cols = st.columns(min(len(columnas_numericas) + 1, 4))
            for i, col in enumerate(columnas_numericas):
                col_idx = i % len(cols)
                total_col = df[col].sum()
                # Formatear el nombre de la columna para mostrarlo limpio
                nombre_limpio = col.replace('_', ' ').title()
                cols[col_idx].metric(nombre_limpio, f"{int(total_col):,}")
            
            # Mostrar total de mesas procesadas
            st.metric("Total Mesas Procesadas", len(df))
        
        st.markdown("---")
        st.subheader("Listado Completo de Actas Registradas")
        st.dataframe(df, use_container_width=True)
    else:
        st.info("Aún no se han registrado actas en el sistema. Registra la primera foto para ver los resultados.")

# ---------------------------------------------------------
# PESTAÑA 2: CONSULTA POR MESA
# ---------------------------------------------------------
with tab2:
    st.header("Buscar Conteo por Número de Mesa")
    
    if not df.empty and 'numero_mesa' in df.columns:
        mesas_disponibles = df['numero_mesa'].astype(str).tolist()
        mesa_seleccionada = st.selectbox("Selecciona o escribe el número de mesa:", mesas_disponibles)
        
        if mesa_seleccionada:
            datos_mesa = df[df['numero_mesa'].astype(str) == str(mesa_seleccionada)]
            if not datos_mesa.empty:
                st.success(f"📌 Detalle de la Mesa N° {mesa_seleccionada}")
                st.dataframe(datos_mesa, use_container_width=True)
    else:
        st.warning("No hay mesas registradas aún para realizar la búsqueda.")
