#!/usr/bin/env python3
"""
Pasos 4-6 de la práctica: ordena los tiempos, arma N(t), hace la regresión,
calcula λ, T½ y la diferencia relativa porcentual con el valor teórico.

Lee datos/tiempos_H3.csv y datos/tiempos_C14.csv (columnas: medicion, t_anios
y opcionalmente t_exacto_anios; se pueden completar a mano si hace falta).
El análisis usa t_anios, que es el tiempo tal como lo muestra la simulación.
Genera:
    decaimiento_beta.xlsx   una hoja por núcleo (datos crudos, tabla ordenada,
                            N y ln N, gráficos) y una hoja "Resumen"
    graficos/*.png          N(t) vs t con el ajuste y ln N vs t con la recta

Regresiones:
    Método A (linealización):  ln N = ln N0 - λ t   -> λ = -pendiente
    Método B (ajuste directo): N(t) = N0 e^(-λ t)   (mínimos cuadrados no lineales)

N(t) se construye con N(0) = N0 (cantidad de mediciones) y, después del
i-ésimo decaimiento en orden de tiempo, N = N0 - i.

Uso:
    python3 analizar.py            # usa la carpeta del script
    python3 analizar.py prueba     # usa prueba/datos y escribe ahí los resultados

También escribe H3_ordenados.xlsx y C14_ordenados.xlsx con los tiempos de menor a mayor.
"""

import csv
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from openpyxl import Workbook
from openpyxl.chart import Reference, ScatterChart, Series
from openpyxl.styles import Alignment, Font, PatternFill
from scipy import stats
from scipy.optimize import curve_fit

CARPETA = Path(__file__).resolve().parent
SALIDA = CARPETA / sys.argv[1] if len(sys.argv) > 1 else CARPETA
DATOS = SALIDA / "datos"
GRAFICOS = SALIDA / "graficos"
EXCEL = SALIDA / "decaimiento_beta.xlsx"

NUCLEOS = {
    "H3": {"nombre": "Hidrógeno-3 (³H → ³He + β)", "corto": "³H", "t_teorico": 12.32},
    "C14": {"nombre": "Carbono-14 (¹⁴C → ¹⁴N + β)", "corto": "¹⁴C", "t_teorico": 5730.0},
}

NEGRITA = Font(bold=True)
ENCABEZADO = PatternFill("solid", fgColor="DDE7F3")


def leer_tiempos(archivo):
    """Devuelve (tiempos en años, textos del recuadro, tiempos exactos); las dos
    últimas son None si el CSV no trae esas columnas."""
    def numero(texto):
        return float(texto.replace(",", ".")) if texto and texto.strip() else None

    with open(archivo, newline="", encoding="utf-8") as f:
        filas = [fila for fila in csv.DictReader(f) if numero(fila.get("t_anios")) is not None]
    tiempos = [numero(fila["t_anios"]) for fila in filas]
    textos = [fila.get("recuadro") for fila in filas]
    exactos = [numero(fila.get("t_exacto_anios")) for fila in filas]
    return (tiempos, (textos if None not in textos else None),
            (exactos if None not in exactos else None))


def analizar(tiempos, t_teorico):
    crudos = np.array(tiempos)
    n0 = len(crudos)
    t_ord = np.sort(crudos)
    # Punto inicial (0, N0) y luego un punto por cada decaimiento.
    t = np.concatenate([[0.0], t_ord])
    N = n0 - np.arange(n0 + 1)

    # Método A: ln N vs t (se excluye el último punto, N = 0).
    positivos = N > 0
    reg = stats.linregress(t[positivos], np.log(N[positivos]))
    lam_a = -reg.slope

    # Método B: ajuste exponencial directo con todos los puntos.
    (n0_b, lam_b), cov = curve_fit(lambda x, a, l: a * np.exp(-l * x), t, N,
                                   p0=[n0, lam_a])
    predicho = n0_b * np.exp(-lam_b * t)
    r2_b = 1 - np.sum((N - predicho) ** 2) / np.sum((N - N.mean()) ** 2)

    def resultado(lam, err, r2, n0_ajuste):
        t_mitad = np.log(2) / lam
        return {"lambda": lam, "lambda_err": err, "r2": r2, "N0_ajuste": n0_ajuste,
                "T_mitad": t_mitad, "T_mitad_err": t_mitad * err / lam,
                "dif_pct": (t_mitad - t_teorico) / t_teorico * 100}

    return {
        "crudos": crudos, "t": t, "N": N, "n0": n0,
        "A": resultado(lam_a, reg.stderr, reg.rvalue ** 2, np.exp(reg.intercept)),
        "B": resultado(lam_b, np.sqrt(cov[1, 1]), r2_b, n0_b),
        # Estimador de máxima verosimilitud: la vida media es el promedio de los tiempos.
        "T_mitad_promedio": np.log(2) * crudos.mean(),
    }


def graficar(clave, info, r):
    GRAFICOS.mkdir(parents=True, exist_ok=True)
    t, N = r["t"], r["N"]
    x = np.linspace(0, t.max(), 300)

    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.step(t, N, where="post", color="0.7", lw=1, label="Núcleos sin decaer")
    ax.plot(t, N, "o", ms=3, color="tab:blue")
    ax.plot(x, r["B"]["N0_ajuste"] * np.exp(-r["B"]["lambda"] * x), color="tab:red",
            label=f"Ajuste $N_0e^{{-\\lambda t}}$, λ = {r['B']['lambda']:.4g} años⁻¹")
    ax.plot(x, r["A"]["N0_ajuste"] * np.exp(-r["A"]["lambda"] * x), "--", color="tab:green",
            label=f"Linealización, λ = {r['A']['lambda']:.4g} años⁻¹")
    ax.set(xlabel="t (años)", ylabel="N", title=f"N(t) — {info['nombre']}")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(GRAFICOS / f"N_vs_t_{clave}.png", dpi=150)
    plt.close(fig)

    pos = N > 0
    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.plot(t[pos], np.log(N[pos]), "o", ms=3, color="tab:blue", label="ln N")
    ax.plot(x, np.log(r["A"]["N0_ajuste"]) - r["A"]["lambda"] * x, color="tab:red",
            label=f"ln N = {np.log(r['A']['N0_ajuste']):.4f} − {r['A']['lambda']:.4g}·t"
                  f"   (R² = {r['A']['r2']:.4f})")
    ax.set(xlabel="t (años)", ylabel="ln N", title=f"Linealización — {info['nombre']}")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(GRAFICOS / f"lnN_vs_t_{clave}.png", dpi=150)
    plt.close(fig)


def graficar_comparativos(resultados):
    """Gráficos que juntan los dos núcleos: curva normalizada e histogramas."""
    colores = {"H3": "tab:blue", "C14": "tab:orange"}

    # N/N0 vs t/T½: con el tiempo medido en vidas medias, los dos núcleos
    # deberían caer sobre la misma curva (1/2)^(t/T½).
    fig, ax = plt.subplots(figsize=(7, 4.5))
    x_max = 0
    for clave, r in resultados.items():
        info = NUCLEOS[clave]
        x = r["t"] / info["t_teorico"]
        x_max = max(x_max, x.max())
        ax.plot(x, r["N"] / r["n0"], "o", ms=3, color=colores[clave], label=info["corto"])
    x = np.linspace(0, x_max, 300)
    ax.plot(x, 0.5 ** x, color="tab:red", label="Ley teórica $(1/2)^{t/T_{1/2}}$")
    for k in range(1, 4):
        ax.plot([k, k, 0], [0, 0.5 ** k, 0.5 ** k], ":", color="0.5", lw=1)
    ax.set(xlabel="t / T½ teórico (cantidad de vidas medias)", ylabel="N / N₀",
           title="Decaimiento de ³H y ¹⁴C en escala de vidas medias")
    ax.set_xlim(0, None)
    ax.set_ylim(0, 1.05)
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(GRAFICOS / "comparacion_normalizada.png", dpi=150)
    plt.close(fig)

    # Histogramas: cuántos núcleos decayeron en cada intervalo de tiempo,
    # comparado con lo que predice la ley exponencial con el T½ teórico.
    fig, ejes = plt.subplots(1, len(resultados), figsize=(11, 4.2), squeeze=False)
    for ax, (clave, r) in zip(ejes[0], resultados.items()):
        info = NUCLEOS[clave]
        ancho = info["t_teorico"] / 2  # intervalos de media vida media
        bordes = np.arange(0, r["crudos"].max() + ancho, ancho)
        ax.hist(r["crudos"], bins=bordes, color=colores[clave], alpha=0.75,
                edgecolor="white", label="Decaimientos medidos")
        lam = np.log(2) / info["t_teorico"]
        esperado = r["n0"] * (np.exp(-lam * bordes[:-1]) - np.exp(-lam * bordes[1:]))
        centros = (bordes[:-1] + bordes[1:]) / 2
        ax.plot(centros, esperado, "o-", color="tab:red", ms=4, label="Esperado (ley exponencial)")
        ax.set(xlabel="t (años)", ylabel="Cantidad de decaimientos",
               title=f"{info['corto']} (intervalos de {ancho:g} años)")
        ax.legend()
        ax.grid(alpha=0.3, axis="y")
    fig.suptitle("Distribución de los tiempos de decaimiento")
    fig.tight_layout()
    fig.savefig(GRAFICOS / "histogramas_tiempos.png", dpi=150)
    plt.close(fig)


def encabezado(ws, fila, columna, textos):
    for i, texto in enumerate(textos):
        celda = ws.cell(fila, columna + i, texto)
        celda.font = NEGRITA
        celda.fill = ENCABEZADO
        celda.alignment = Alignment(horizontal="center", wrap_text=True)


def numero_celda(t):
    """Enteros sin decimales (como los muestra la simulación), el resto tal cual."""
    t = float(t)
    return int(t) if t.is_integer() else round(t, 6)


def hoja_nucleo(wb, clave, info, r):
    ws = wb.create_sheet(clave)
    ws["A1"] = info["nombre"]
    ws["A1"].font = Font(bold=True, size=13)

    # Datos crudos en el orden en que se midieron (columnas A-D).
    encabezado(ws, 3, 1, ["Medición", "Recuadro", "t (años)", "t exacto (años)"])
    for i, t in enumerate(r["crudos"], 1):
        ws.cell(3 + i, 1, i)
        if r["textos"]:
            ws.cell(3 + i, 2, r["textos"][i - 1])
        ws.cell(3 + i, 3, numero_celda(t))
        if r["exactos"]:
            ws.cell(3 + i, 4, round(float(r["exactos"][i - 1]), 3))

    # Tabla del paso 4: tiempos ordenados y núcleos sin decaer (columnas F-I).
    encabezado(ws, 3, 6, ["Orden", "t ordenado (años)", "N", "ln N"])
    for i, (t, n) in enumerate(zip(r["t"], r["N"])):
        fila = 4 + i
        ws.cell(fila, 6, i)
        ws.cell(fila, 7, numero_celda(t))
        ws.cell(fila, 8, int(n))
        if n > 0:
            ws.cell(fila, 9, round(float(np.log(n)), 6))

    for col, ancho in zip("ABCDEFGHI", [10, 11, 10, 15, 3, 8, 17, 7, 10]):
        ws.column_dimensions[col].width = ancho

    ultima = 3 + len(r["t"])
    for titulo, col_y, ancla, nombre_y in [(f"N(t) — {info['corto']}", 8, "K3", "N"),
                                           (f"ln N vs t — {info['corto']}", 9, "K22", "ln N")]:
        graf = ScatterChart()
        graf.title = titulo
        graf.style = 13
        graf.x_axis.title = "t (años)"
        graf.y_axis.title = nombre_y
        serie = Series(Reference(ws, min_col=col_y, min_row=4, max_row=ultima),
                       Reference(ws, min_col=7, min_row=4, max_row=ultima), title=nombre_y)
        serie.marker.symbol = "circle"
        serie.marker.size = 5
        serie.marker.graphicalProperties.solidFill = "1F77B4"
        serie.marker.graphicalProperties.line.solidFill = "1F77B4"
        serie.graphicalProperties.line.noFill = True
        graf.series.append(serie)
        graf.legend = None
        graf.width, graf.height = 16, 8.5
        ws.add_chart(graf, ancla)


def hoja_resumen(wb, resultados):
    ws = wb.create_sheet("Resumen", 0)
    ws["A1"] = "Resumen — Simulaciones numéricas del decaimiento β"
    ws["A1"].font = Font(bold=True, size=13)
    ws["A2"] = "T½ = ln2 / λ      ΔT½ = (T½exp − T½teórico) / T½teórico × 100 %"

    columnas = ["Núcleo", "Método", "N0", "λ (años⁻¹)", "error λ", "R²", "N0 del ajuste",
                "T½ exp (años)", "error T½", "T½ teórico (años)", "ΔT½ (%)"]
    encabezado(ws, 4, 1, columnas)
    fila = 5
    for clave, r in resultados.items():
        info = NUCLEOS[clave]
        for metodo, nombre in [("A", "Linealización ln N vs t"), ("B", "Ajuste exponencial")]:
            m = r[metodo]
            valores = [info["corto"], nombre, r["n0"], m["lambda"], m["lambda_err"], m["r2"],
                       m["N0_ajuste"], m["T_mitad"], m["T_mitad_err"], info["t_teorico"],
                       m["dif_pct"]]
            for c, v in enumerate(valores, 1):
                ws.cell(fila, c, float(v) if isinstance(v, (np.floating, float)) else v)
            fila += 1

    fila += 1
    ws.cell(fila, 1, "Control: T½ = ln2 · (promedio de los tiempos), estimador de máxima verosimilitud").font = NEGRITA
    for clave, r in resultados.items():
        fila += 1
        t_teo = NUCLEOS[clave]["t_teorico"]
        ws.cell(fila, 1, NUCLEOS[clave]["corto"])
        ws.cell(fila, 8, float(r["T_mitad_promedio"]))
        ws.cell(fila, 10, t_teo)
        ws.cell(fila, 11, float((r["T_mitad_promedio"] - t_teo) / t_teo * 100))

    for col, ancho in zip("ABCDEFGHIJK", [8, 24, 6, 12, 11, 9, 13, 14, 10, 16, 10]):
        ws.column_dimensions[col].width = ancho
    for fila_celdas in ws.iter_rows(min_row=5, max_row=fila):
        for celda in fila_celdas:
            if isinstance(celda.value, float):
                celda.number_format = "0.0000" if abs(celda.value) >= 0.01 else "0.000E+00"


def guardar_ordenados(archivo, info, r):
    """Tabla del paso 4 en su propio Excel: tiempos de menor a mayor y núcleos sin decaer."""
    orden = np.argsort(r["crudos"], kind="stable")
    wb = Workbook()
    ws = wb.active
    ws.title = "Datos ordenados"
    ws["A1"] = f"{info['nombre']} — tiempos de desintegración ordenados de menor a mayor"
    ws["A1"].font = Font(bold=True, size=13)
    ws["A2"] = f"N0 = {r['n0']} núcleos. N = núcleos que quedan sin decaer después de cada tiempo."
    encabezado(ws, 4, 1, ["Orden", "t (años)", "Como lo muestra el simulador", "N", "ln N"])
    ws.append([0, 0, "", r["n0"], round(float(np.log(r["n0"])), 6)])
    for k, i in enumerate(orden, 1):
        n = r["n0"] - k
        ws.append([k, numero_celda(r["crudos"][i]), r["textos"][i] if r["textos"] else "",
                   n, round(float(np.log(n)), 6) if n > 0 else None])
    for col, ancho in zip("ABCDE", [8, 11, 28, 6, 11]):
        ws.column_dimensions[col].width = ancho
    for fila in ws.iter_rows(min_row=5, min_col=3, max_col=3):
        fila[0].alignment = Alignment(horizontal="right")
    ws.freeze_panes = "A5"
    wb.save(archivo)


def main():
    resultados = {}
    for clave, info in NUCLEOS.items():
        archivo = DATOS / f"tiempos_{clave}.csv"
        if not archivo.exists():
            continue
        tiempos, textos, exactos = leer_tiempos(archivo)
        if len(tiempos) < 3:
            print(f"{archivo.name}: muy pocos datos, se omite.")
            continue
        r = analizar(tiempos, info["t_teorico"])
        r["textos"], r["exactos"] = textos, exactos
        guardar_ordenados(SALIDA / f"{clave}_ordenados.xlsx", info, r)
        resultados[clave] = r
        graficar(clave, info, r)

        print(f"\n{info['nombre']}  (N0 = {r['n0']})")
        for metodo, nombre in [("A", "Linealización"), ("B", "Ajuste exponencial")]:
            m = r[metodo]
            print(f"  {nombre:20s} λ = {m['lambda']:.5g} ± {m['lambda_err']:.2g} años⁻¹"
                  f"   T½ = {m['T_mitad']:.5g} ± {m['T_mitad_err']:.2g} años"
                  f"   R² = {m['r2']:.4f}   ΔT½ = {m['dif_pct']:+.2f} %")
        print(f"  {'ln2 · promedio':20s} T½ = {r['T_mitad_promedio']:.5g} años"
              f"   (teórico {info['t_teorico']} años)")

    if not resultados:
        print("No hay datos en la carpeta datos/. Corré primero medir_decaimiento.py")
        return

    graficar_comparativos(resultados)

    wb = Workbook()
    wb.remove(wb.active)
    hoja_resumen(wb, resultados)
    for clave, r in resultados.items():
        hoja_nucleo(wb, clave, NUCLEOS[clave], r)
    wb.save(EXCEL)
    print(f"\nPlanilla: {EXCEL.name}    Gráficos: {GRAFICOS.name}/")


if __name__ == "__main__":
    main()
