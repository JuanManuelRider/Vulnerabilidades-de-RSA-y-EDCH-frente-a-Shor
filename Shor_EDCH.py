import numpy as np
from math import pi
from collections import defaultdict

from qiskit import QuantumCircuit
from qiskit.transpiler import generate_preset_pass_manager
from qiskit_ibm_runtime import (
    QiskitRuntimeService,
    SamplerV2 as Sampler
)


# ============================================================
# CONFIGURACIÓN DE LA CUENTA DE IBM QUANTUM
# ============================================================

# Esta operación solo debe ejecutarse una vez para guardar
# las credenciales en el equipo.
#
# No debe incluirse el token real en el código entregado
# junto con el TFM.

QiskitRuntimeService.save_account(
    channel="ibm_quantum_platform",
    token="x7eHYrkp26FbYn_VG1yBZS26hBXdN64861S_n1j_874K",
    overwrite=True,
    set_as_default=True
)


# ============================================================
# OPERACIONES SOBRE LA CURVA ELÍPTICA
# ============================================================

# El valor None representa el punto del infinito O.

Punto = tuple[int, int] | None


def inverso_modular(valor: int, modulo: int) -> int:
    """
    Calcula el inverso modular de valor módulo modulo.
    """

    valor %= modulo

    if valor == 0:
        raise ZeroDivisionError(
            "El valor cero no posee inverso modular."
        )

    return pow(valor, -1, modulo)


def sumar_puntos(
    punto_1: Punto,
    punto_2: Punto,
    primo: int,
    coeficiente_a: int
) -> Punto:
    """
    Suma dos puntos pertenecientes a una curva elíptica:

        y^2 = x^3 + a*x + b mod p

    El coeficiente b no aparece directamente en las fórmulas
    de suma, aunque determina qué puntos pertenecen a la curva.
    """

    # O + P = P.
    if punto_1 is None:
        return punto_2

    # P + O = P.
    if punto_2 is None:
        return punto_1

    x_1, y_1 = punto_1
    x_2, y_2 = punto_2

    # P + (-P) = O.
    if x_1 == x_2 and (y_1 + y_2) % primo == 0:
        return None

    # Doblado de un punto: P + P.
    if punto_1 == punto_2:

        if y_1 % primo == 0:
            return None

        numerador = (3 * x_1**2 + coeficiente_a) % primo
        denominador = inverso_modular(2 * y_1, primo)

    # Suma de dos puntos diferentes.
    else:
        numerador = (y_2 - y_1) % primo
        denominador = inverso_modular(x_2 - x_1, primo)

    pendiente = (numerador * denominador) % primo

    x_3 = (pendiente**2 - x_1 - x_2) % primo
    y_3 = (pendiente * (x_1 - x_3) - y_1) % primo

    return x_3, y_3


def multiplicar_punto(
    escalar: int,
    punto: Punto,
    primo: int,
    coeficiente_a: int
) -> Punto:
    """
    Calcula escalar * punto mediante el método de
    doble y suma.
    """

    if escalar < 0:
        raise ValueError(
            "Esta implementación espera un escalar no negativo."
        )

    resultado = None
    sumando = punto
    valor = escalar

    while valor > 0:

        if valor & 1:
            resultado = sumar_puntos(
                resultado,
                sumando,
                primo,
                coeficiente_a
            )

        sumando = sumar_puntos(
            sumando,
            sumando,
            primo,
            coeficiente_a
        )

        valor >>= 1

    return resultado


def punto_pertenece_curva(
    punto: Punto,
    primo: int,
    coeficiente_a: int,
    coeficiente_b: int
) -> bool:
    """
    Comprueba si un punto pertenece a la curva elíptica.
    """

    if punto is None:
        return True

    x, y = punto

    lado_izquierdo = y**2 % primo

    lado_derecho = (
        x**3
        + coeficiente_a * x
        + coeficiente_b
    ) % primo

    return lado_izquierdo == lado_derecho


# ============================================================
# FUNCIONES DEL CIRCUITO CUÁNTICO
# ============================================================

def aplicar_superposicion(
    circuito: QuantumCircuit,
    qubits: list[int]
) -> None:
    """
    Aplica una puerta Hadamard a todos los cúbits indicados.

    Los dos registros pasan a representar una superposición
    uniforme de pares |x,y>.
    """

    for qubit in qubits:
        circuito.h(qubit)


def introducir_fase_artificial(
    circuito: QuantumCircuit,
    qubits: list[int],
    numerador_fase: int,
    orden: int
) -> None:
    """
    Introduce una fase asociada a la fracción:

        numerador_fase / orden

    La fase aplicada al cúbit j del registro es:

        2*pi*numerador_fase*2^j / orden

    En una implementación completa, esta información aparecería
    tras evaluar reversiblemente la función:

        f(x,y) = xG + yQ

    y medir o descartar el registro que contiene el punto.

    Aquí se introduce directamente para mantener el circuito
    suficientemente pequeño para su ejecución experimental.
    """

    for posicion, qubit in enumerate(qubits):

        fase = (
            2
            * np.pi
            * numerador_fase
            * (2**posicion)
            / orden
        )

        circuito.p(fase, qubit)


def aplicar_qft_inversa(
    circuito: QuantumCircuit,
    qubits: list[int]
) -> None:
    """
    Aplica manualmente la Transformada Cuántica de Fourier
    inversa sobre los cúbits indicados.
    """

    numero_qubits = len(qubits)

    # Inversión del orden mediante puertas SWAP.
    for posicion in range(numero_qubits // 2):

        circuito.swap(
            qubits[posicion],
            qubits[numero_qubits - posicion - 1]
        )

    # Puertas de fase controladas inversas y Hadamard.
    for objetivo_local in reversed(range(numero_qubits)):

        objetivo = qubits[objetivo_local]

        for control_local in reversed(
            range(objetivo_local + 1, numero_qubits)
        ):

            control = qubits[control_local]

            angulo = -pi / (
                2 ** (control_local - objetivo_local)
            )

            circuito.cp(
                angulo,
                control,
                objetivo
            )

        circuito.h(objetivo)


def crear_circuito_ecdlp_reducido(
    orden: int,
    clave_privada: int,
    muestra_u: int,
    numero_qubits_registro: int
) -> QuantumCircuit:
    """
    Construye una demostración reducida del algoritmo de Shor
    aplicado al logaritmo discreto sobre curvas elípticas.

    La relación pública es:

        Q = kG

    El algoritmo completo evalúa:

        f(x,y) = xG + yQ

    y obtiene pares de frecuencias (u,v) que satisfacen,
    según la convención utilizada:

        v = k*u mod n

    En esta versión se escoge artificialmente un valor u y se
    calcula:

        v = k*u mod n

    Posteriormente, ambas fases se codifican en dos registros
    independientes y se aplica la TCF inversa.

    Parámetros:
        orden:
            Orden n del punto generador G.

        clave_privada:
            Valor k que se pretende recuperar.

        muestra_u:
            Valor u usado para crear una muestra espectral.

        numero_qubits_registro:
            Número de cúbits empleado en cada registro.
    """

    if orden <= 2:
        raise ValueError(
            "El orden del grupo debe ser mayor que dos."
        )

    clave_privada %= orden
    muestra_u %= orden

    if muestra_u == 0:
        raise ValueError(
            "La muestra u no puede ser cero."
        )

    # La relación que permitirá recuperar k.
    muestra_v = (
        clave_privada * muestra_u
    ) % orden

    total_qubits = 2 * numero_qubits_registro

    circuito = QuantumCircuit(
        total_qubits,
        total_qubits
    )

    registro_u = list(
        range(numero_qubits_registro)
    )

    registro_v = list(
        range(
            numero_qubits_registro,
            total_qubits
        )
    )

    # 1. Superposición uniforme de ambos registros.
    aplicar_superposicion(
        circuito,
        registro_u + registro_v
    )

    circuito.barrier()

    # 2. Introducción artificial de las fases relacionadas.
    introducir_fase_artificial(
        circuito,
        registro_u,
        muestra_u,
        orden
    )

    introducir_fase_artificial(
        circuito,
        registro_v,
        muestra_v,
        orden
    )

    circuito.barrier()

    # 3. TCF inversa sobre cada registro.
    aplicar_qft_inversa(
        circuito,
        registro_u
    )

    aplicar_qft_inversa(
        circuito,
        registro_v
    )

    circuito.barrier()

    # 4. Medición.
    circuito.measure(
        range(total_qubits),
        range(total_qubits)
    )

    return circuito


# ============================================================
# POSPROCESADO CLÁSICO
# ============================================================

def convertir_medicion_a_residuo(
    medicion: int,
    orden: int,
    numero_qubits: int
) -> int:
    """
    Convierte un resultado de medida z en una aproximación
    del numerador de fase t mediante:

        z / 2^m ≈ t / n

    Por tanto:

        t ≈ z*n / 2^m
    """

    dimension = 2**numero_qubits

    residuo = round(
        medicion * orden / dimension
    )

    return residuo % orden


def separar_estado_medido(
    estado_binario: str,
    numero_qubits_registro: int
) -> tuple[int, int]:
    """
    Separa el resultado conjunto en los valores medidos de
    los registros u y v.

    Qiskit representa los bits clásicos desde el índice más
    alto hasta el más bajo al mostrar la cadena binaria.

    Como el registro u ocupa los cúbits menos significativos,
    se utiliza una máscara para recuperarlo.
    """

    estado_limpio = estado_binario.replace(" ", "")

    valor_completo = int(
        estado_limpio,
        2
    )

    mascara = (
        1 << numero_qubits_registro
    ) - 1

    medicion_u = valor_completo & mascara

    medicion_v = (
        valor_completo
        >> numero_qubits_registro
    ) & mascara

    return medicion_u, medicion_v


def obtener_clave_privada(
    conteos: dict[str, int],
    orden: int,
    numero_qubits_registro: int
) -> tuple[int, dict[int, int]]:
    """
    Recupera candidatos para la clave privada a partir de los
    resultados de medida.

    Para cada par aproximado (u,v), se utiliza:

        v = k*u mod n

    Si u es invertible módulo n:

        k = v*u^(-1) mod n

    Los candidatos se ponderan usando la frecuencia con la que
    aparece cada resultado.
    """

    frecuencias_candidatos: dict[int, int] = defaultdict(int)

    resultados_ordenados = sorted(
        conteos.items(),
        key=lambda elemento: elemento[1],
        reverse=True
    )

    for estado, frecuencia in resultados_ordenados:

        medicion_u, medicion_v = separar_estado_medido(
            estado,
            numero_qubits_registro
        )

        u = convertir_medicion_a_residuo(
            medicion_u,
            orden,
            numero_qubits_registro
        )

        v = convertir_medicion_a_residuo(
            medicion_v,
            orden,
            numero_qubits_registro
        )

        if u == 0:
            continue

        try:
            inverso_u = pow(
                u,
                -1,
                orden
            )
        except ValueError:
            # El valor u no es invertible módulo n.
            continue

        candidato = (
            v * inverso_u
        ) % orden

        frecuencias_candidatos[candidato] += frecuencia

    if not frecuencias_candidatos:
        raise ValueError(
            "No se han obtenido muestras válidas para recuperar k."
        )

    mejor_candidato = max(
        frecuencias_candidatos,
        key=frecuencias_candidatos.get
    )

    return mejor_candidato, dict(
        sorted(
            frecuencias_candidatos.items(),
            key=lambda elemento: elemento[1],
            reverse=True
        )
    )


def mostrar_muestras_principales(
    conteos: dict[str, int],
    orden: int,
    numero_qubits_registro: int,
    numero_resultados: int = 10
) -> None:
    """
    Muestra los resultados más frecuentes y su conversión
    aproximada a pares (u,v).
    """

    resultados_ordenados = sorted(
        conteos.items(),
        key=lambda elemento: elemento[1],
        reverse=True
    )

    print("\nMuestras principales:")

    print(
        "Estado".ljust(25),
        "medida u".ljust(10),
        "medida v".ljust(10),
        "u".ljust(5),
        "v".ljust(5),
        "frecuencia"
    )

    for estado, frecuencia in resultados_ordenados[:numero_resultados]:

        medicion_u, medicion_v = separar_estado_medido(
            estado,
            numero_qubits_registro
        )

        u = convertir_medicion_a_residuo(
            medicion_u,
            orden,
            numero_qubits_registro
        )

        v = convertir_medicion_a_residuo(
            medicion_v,
            orden,
            numero_qubits_registro
        )

        print(
            estado.ljust(25),
            str(medicion_u).ljust(10),
            str(medicion_v).ljust(10),
            str(u).ljust(5),
            str(v).ljust(5),
            frecuencia
        )


# ============================================================
# PARÁMETROS DE LA CURVA ELÍPTICA
# ============================================================

# Curva:
#
#     E: y^2 = x^3 + 2x + 2 mod 17

p = 17
a = 2
b = 2

# Punto generador de orden 19.
G = (5, 1)

# Orden del subgrupo generado por G.
n = 19

# Clave privada que se utilizará en el ejemplo.
k_secreto = 7

# Clave pública:
#
#     Q = kG

Q = multiplicar_punto(
    k_secreto,
    G,
    p,
    a
)

# Se escoge u = 1 para generar una relación sencilla:
#
#     v = k*u mod n = 7

u_artificial = 1

# Cada registro utiliza 5 cúbits:
#
#     2^5 = 32 > 19
#
# El circuito completo utiliza 10 cúbits.
m = 5


# ============================================================
# COMPROBACIÓN CLÁSICA DE LOS PARÁMETROS
# ============================================================

if not punto_pertenece_curva(
    G,
    p,
    a,
    b
):
    raise ValueError(
        "El punto G no pertenece a la curva."
    )

if not punto_pertenece_curva(
    Q,
    p,
    a,
    b
):
    raise ValueError(
        "El punto Q no pertenece a la curva."
    )

if multiplicar_punto(
    n,
    G,
    p,
    a
) is not None:
    raise ValueError(
        "El valor n indicado no es el orden de G."
    )

print("Curva elíptica:")
print(
    f"E: y^2 = x^3 + {a}x + {b} mod {p}"
)

print("\nPunto generador G:", G)
print("Orden de G:", n)
print("Clave pública Q:", Q)
print("Relación comprobada: Q =", k_secreto, "G")


# ============================================================
# CREACIÓN DEL CIRCUITO
# ============================================================

qc = crear_circuito_ecdlp_reducido(
    orden=n,
    clave_privada=k_secreto,
    muestra_u=u_artificial,
    numero_qubits_registro=m
)

print("\nCircuito antes de la transpilación:")
print(qc.draw("text"))


# ============================================================
# CONEXIÓN CON IBM QUANTUM
# ============================================================

service = QiskitRuntimeService()

backend = service.least_busy(
    operational=True,
    simulator=False,
    min_num_qubits=2 * m
)

print("\nBackend seleccionado:", backend.name)


# ============================================================
# TRANSPILACIÓN
# ============================================================

gestor_transpilacion = generate_preset_pass_manager(
    backend=backend,
    optimization_level=3
)

circuito_isa = gestor_transpilacion.run(qc)

print(
    "Número de cúbits físicos del circuito transpilado:",
    circuito_isa.num_qubits
)

print(
    "Profundidad tras la transpilación:",
    circuito_isa.depth()
)


# ============================================================
# EJECUCIÓN EN HARDWARE DE IBM
# ============================================================

sampler = Sampler(mode=backend)

trabajo = sampler.run(
    [circuito_isa],
    shots=4096
)

print(
    "\nIdentificador del trabajo:",
    trabajo.job_id()
)

resultado = trabajo.result()

conteos = resultado[0].data.c.get_counts()

print("\nResultados de medida:")
print(conteos)


# ============================================================
# GUARDADO DE RESULTADOS
# ============================================================

with open(
    "Resultados_Shor_ECDLP.txt",
    "w",
    encoding="utf-8"
) as archivo:

    archivo.write(
        "Resultados de Shor para logaritmo discreto elíptico\n"
    )

    archivo.write(
        "==================================================\n\n"
    )

    archivo.write(
        f"Curva: y^2 = x^3 + {a}x + {b} mod {p}\n"
    )

    archivo.write(f"G = {G}\n")
    archivo.write(f"Q = {Q}\n")
    archivo.write(f"Orden de G = {n}\n\n")

    for estado, frecuencia in sorted(
        conteos.items(),
        key=lambda elemento: elemento[1],
        reverse=True
    ):
        archivo.write(
            f"{estado}: {frecuencia}\n"
        )

print(
    "\nLos resultados se han guardado en "
    "'Resultados_Shor_ECDLP.txt'."
)


# ============================================================
# RECUPERACIÓN CLÁSICA DE LA CLAVE PRIVADA
# ============================================================

mostrar_muestras_principales(
    conteos,
    orden=n,
    numero_qubits_registro=m
)

clave_recuperada, candidatos = obtener_clave_privada(
    conteos,
    orden=n,
    numero_qubits_registro=m
)

print("\nCandidatos obtenidos:")
print(candidatos)

print(
    "\nClave privada utilizada:",
    k_secreto
)

print(
    "Clave privada recuperada:",
    clave_recuperada
)

Q_recuperado = multiplicar_punto(
    clave_recuperada,
    G,
    p,
    a
)

print(
    "Punto obtenido con la clave recuperada:",
    Q_recuperado
)

print(
    "Clave pública esperada:",
    Q
)

if Q_recuperado == Q:
    print(
        "Comprobación correcta: "
        "Q = clave_recuperada * G."
    )
else:
    print(
        "La muestra dominante no ha permitido recuperar "
        "correctamente la clave debido al ruido."
    )