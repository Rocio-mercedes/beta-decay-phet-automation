#!/usr/bin/env python3
"""
Automatiza los pasos 1-3 de la práctica "Simulaciones numéricas del decaimiento β".

Abre la simulación PhET "Desintegración Beta", va a la pestaña "Un átomo",
elige el núcleo (Hidrógeno-3 o Carbono-14), aprieta "Reponer Núcleos",
espera a que el núcleo decaiga y anota el tiempo de decaimiento. Repite N veces
(120 por defecto) y guarda los tiempos en datos/tiempos_<núcleo>.csv.
Al terminar llama a analizar.py, que ordena los tiempos, arma N(t), hace la
regresión y genera decaimiento_beta.xlsx (se abre con LibreOffice).

Cómo se lee el tiempo:
    La simulación es un programa Java que corre dentro del navegador y dibuja
    todo como una imagen, así que no hay texto que leer en la página. Por eso el
    script intercepta el valor interno que alimenta el recuadro "Tiempo de
    decaimiento" y lo redondea igual que la simulación (años enteros, o días
    si es menos de un año). Así se anota el mismo número que se ve; los días se
    pasan a años para el análisis.
    También guarda el tiempo de vida exacto que sorteó la simulación, sin redondeo.

Uso:
    python3 medir_decaimiento.py                 # H-3 y C-14, 120 mediciones cada uno
    python3 medir_decaimiento.py --prueba        # 10 de cada uno en la carpeta prueba/,
                                                 # con captura del recuadro de cada medición
    python3 medir_decaimiento.py --nucleo H3     # solo tritio
    python3 medir_decaimiento.py --oculto        # sin mostrar la ventana del navegador

Requisitos (una sola vez):
    pip install --user playwright
    (usa el Google Chrome instalado; si no lo hay: python3 -m playwright install chromium)
"""

import argparse
import csv
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from playwright.sync_api import Error as ErrorNavegador, sync_playwright

URL = ("https://phet.colorado.edu/sims/cheerpj/nuclear-physics/latest/"
       "nuclear-physics.html?simulation=beta-decay&locale=es")

CARPETA = Path(__file__).resolve().parent

# Milisegundos por año: el recuadro de la simulación usa 3.16e10; el tiempo de
# vida sorteado usa el año trópico (365.2422 días).
MS_POR_ANIO_RECUADRO = 3.16e10
MS_POR_ANIO = 365.2422 * 24 * 3600 * 1000
MS_POR_DIA = 24 * 3600 * 1000

# Posiciones (en píxeles) de los controles dentro de la simulación, que siempre
# se dibuja en un lienzo de 1024x768 anclado arriba a la izquierda.
PESTANIA_UN_ATOMO = (240, 51)
BOTON_REPONER = (661, 272)
RECUADRO_TIEMPO = {"x": 22, "y": 82, "width": 140, "height": 46}

NUCLEOS = {
    "H3": {"nombre": "Hidrógeno-3", "radio": (831, 229), "protones": 1},
    "C14": {"nombre": "Carbono-14", "radio": (831, 348), "protones": 6},
}

# Se inyecta antes de que cargue la simulación.
#  - Cada vez que un núcleo sortea su tiempo de vida, lo guarda en window.__vidas
#    y deja el núcleo en window.__ultimo para poder preguntar si ya decayó.
#  - Cada vez que se actualiza el recuadro "Tiempo de decaimiento", guarda el
#    valor (en ms) en window.__recuadro.
GANCHO_JS = """
(() => {
  window.__vidas = [];
  window.__ultimo = null;
  window.__recuadro = 0;
  function espiar(campo, alCambiar) {
    const oculto = '__' + campo;
    Object.defineProperty(Object.prototype, campo, {
      configurable: true,
      get() { return this[oculto] === undefined ? 0 : this[oculto]; },
      set(v) {
        Object.defineProperty(this, oculto,
          {value: v, writable: true, configurable: true, enumerable: false});
        alCambiar(this, v);
      }
    });
  }
  espiar('_totalUndecayedLifetime16', (nucleo, v) => {
    if (v > 0) {
      window.__vidas.push({ms: v, protones: nucleo._numProtons9});
      window.__ultimo = nucleo;
    }
  });
  espiar('_currentTimeInMilliseconds38', (recuadro, v) => { window.__recuadro = v; });
})();
"""


def esperar(condicion, timeout, intervalo=0.2):
    """Repite condicion() hasta que devuelva algo verdadero o se acabe el tiempo."""
    limite = time.time() + timeout
    while time.time() < limite:
        valor = condicion()
        if valor:
            return valor
        time.sleep(intervalo)
    return None


def cantidad_vidas(pagina):
    return pagina.evaluate("window.__vidas ? window.__vidas.length : 0")


def ultima_vida(pagina):
    return pagina.evaluate("window.__vidas[window.__vidas.length - 1]")


def ultimo_decayo(pagina):
    return pagina.evaluate(
        "(() => { const o = window.__ultimo;"
        " return !!o && o._numProtons9 !== o._origNumProtons11; })()")


def texto_recuadro(anios):
    """Años escritos como en la página: "12 años" o, desde 1000, "29.02 x 10³ años"."""
    if anios < 1000:
        return f"{anios} años"
    mantisa = f"{anios / 1000:.3f}".rstrip("0").rstrip(".")
    return f"{mantisa} x 10³ años"


def valor_recuadro(pagina):
    """Devuelve (texto como lo muestra el recuadro, valor en años)."""
    ms = pagina.evaluate("window.__recuadro")
    anios = ms / MS_POR_ANIO_RECUADRO
    if anios >= 1:
        return texto_recuadro(round(anios)), int(round(anios))
    dias = round(ms / MS_POR_DIA)
    return f"{dias} días", round(dias / 365.25, 4)


def abrir_simulacion(pagina):
    print("Abriendo la simulación (tarda unos 20-40 s en cargar)...")
    pagina.goto(URL, timeout=120_000)
    # Al terminar de cargar, la simulación crea el primer núcleo de "Un átomo".
    if not esperar(lambda: cantidad_vidas(pagina) > 0, timeout=180):
        sys.exit("La simulación no terminó de cargar. Probá de nuevo.")
    time.sleep(3)  # margen para que se dibuje la interfaz
    pagina.mouse.click(*PESTANIA_UN_ATOMO)
    time.sleep(1.5)


def reponer_nucleo(pagina, protones):
    """Aprieta "Reponer Núcleos" y devuelve el tiempo de vida sorteado (en ms)."""
    for _ in range(5):
        antes = cantidad_vidas(pagina)
        pagina.mouse.click(*BOTON_REPONER)
        if esperar(lambda: cantidad_vidas(pagina) > antes, timeout=5):
            vida = ultima_vida(pagina)
            if vida["protones"] == protones:
                return vida["ms"]
    sys.exit("No se pudo reponer el núcleo. ¿Se movió la ventana o cambió la simulación?")


def medir(pagina, clave, n, capturas):
    nucleo = NUCLEOS[clave]
    print(f"\n=== {nucleo['nombre']}: {n} mediciones ===")
    pagina.mouse.click(*nucleo["radio"])  # "Elegir Núcleo"
    time.sleep(1.5)

    filas = []
    for i in range(1, n + 1):
        try:
            filas.append(medir_una(pagina, clave, i, n, capturas))
        except ErrorNavegador:
            print(f"\n¡Se cerró el navegador! Se guardan las {len(filas)} mediciones hechas.")
            return filas, False
    return filas, True


def medir_una(pagina, clave, i, n, capturas):
    """Repone el núcleo, espera el decaimiento y devuelve la fila medida."""
    nucleo = NUCLEOS[clave]
    ms = reponer_nucleo(pagina, nucleo["protones"])
    if not esperar(lambda: ultimo_decayo(pagina), timeout=900, intervalo=0.25):
        sys.exit("El núcleo no decayó en 15 minutos; se corta la medición.")
    time.sleep(0.4)  # deja que el recuadro termine de actualizarse
    texto, anios = valor_recuadro(pagina)
    exacto = ms / MS_POR_ANIO
    print(f"  {nucleo['nombre']}  {i:3d}/{n}   recuadro: {texto:>10}"
          f"   (exacto {exacto:.3f} años)")
    if capturas:
        capturas.mkdir(parents=True, exist_ok=True)
        pagina.screenshot(path=str(capturas / f"{clave}_{i:03d}.png"), clip=RECUADRO_TIEMPO)
    return i, anios, texto, exacto


def guardar_csv(datos, clave, filas):
    datos.mkdir(parents=True, exist_ok=True)
    archivo = datos / f"tiempos_{clave}.csv"
    if archivo.exists():  # nunca pisar datos anteriores
        sello = datetime.fromtimestamp(archivo.stat().st_mtime).strftime("%Y%m%d-%H%M%S")
        archivo.rename(datos / f"tiempos_{clave}_anterior_{sello}.csv")
    with open(archivo, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["medicion", "t_anios", "recuadro", "t_exacto_anios"])
        for i, anios, texto, exacto in filas:
            w.writerow([i, anios, texto, f"{exacto:.6f}"])
    print(f"Guardado: {archivo}")


def main():
    ap = argparse.ArgumentParser(description="Mide tiempos de decaimiento β en la simulación PhET.")
    ap.add_argument("--nucleo", choices=["H3", "C14", "ambos"], default="ambos")
    ap.add_argument("-n", type=int, help="mediciones por núcleo (default 120; 10 con --prueba)")
    ap.add_argument("--prueba", action="store_true",
                    help="corrida corta en la carpeta prueba/, con capturas del recuadro")
    ap.add_argument("--oculto", action="store_true", help="no mostrar la ventana del navegador")
    args = ap.parse_args()
    sys.stdout.reconfigure(line_buffering=True)  # mostrar el progreso en el momento

    n = args.n or (10 if args.prueba else 120)
    salida = CARPETA / "prueba" if args.prueba else CARPETA
    capturas = salida / "capturas" if args.prueba else None
    claves = ["H3", "C14"] if args.nucleo == "ambos" else [args.nucleo]

    with sync_playwright() as p:
        try:
            navegador = p.chromium.launch(channel="chrome", headless=args.oculto)
        except Exception:
            navegador = p.chromium.launch(headless=args.oculto)
        pagina = navegador.new_page(viewport={"width": 1024, "height": 768})
        pagina.add_init_script(GANCHO_JS)
        abrir_simulacion(pagina)
        for clave in claves:
            filas, completo = medir(pagina, clave, n, capturas)
            if filas:
                guardar_csv(salida / "datos", clave, filas)
            if not completo:
                sys.exit("Medición cortada. Volvé a correr el script (no cierres la ventana de"
                         " Chrome mientras mide, o usá --oculto).")
        navegador.close()

    print("\nAnalizando...")
    subprocess.run([sys.executable, str(CARPETA / "analizar.py"), str(salida)], check=False)


if __name__ == "__main__":
    main()
