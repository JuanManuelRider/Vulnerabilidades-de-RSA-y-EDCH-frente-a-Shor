import numpy as np
from math import gcd, pi

from qiskit import QuantumCircuit
from qiskit.transpiler import generate_preset_pass_manager
from qiskit_ibm_runtime import (QiskitRuntimeService,SamplerV2 as Sampler)


# ============================================================
# CONFIGURACIÓN DE LA CUENTA DE IBM QUANTUM
# ============================================================
QiskitRuntimeService.save_account(channel="ibm_quantum_platform",token="INTRODUCIR TOKEN",overwrite=True,set_as_default=True)


# ============================================================
# FUNCIONES DEL CIRCUITO CUÁNTICO
# ============================================================

def aplicar_superposicion(circuito: QuantumCircuit,numero_qubits: int) -> None:
    """
    Aplica una puerta Hadamard a todos los cúbits del registro.

    De esta forma, el registro pasa del estado inicial |0...0>
    a una superposición uniforme de todos los estados posibles.
    """

    for qubit in range(numero_qubits):
        circuito.h(qubit)


def introducir_periodicidad(circuito: QuantumCircuit,periodo: int,numero_qubits: int) -> None:
    """
    Introduce artificialmente una fase asociada al período indicado.

    En una implementación completa de Shor, esta información de fase
    sería generada por las operaciones de exponenciación modular
    controlada. En esta versión reducida se introduce directamente
    para evitar un circuito excesivamente profundo.

    La fase aplicada al cúbit j es:

        2*pi*2^j / periodo
    """

    for qubit in range(numero_qubits):
        fase = 2 * np.pi * (2**qubit) / periodo
        circuito.p(fase, qubit)


def aplicar_qft_inversa(circuito: QuantumCircuit,numero_qubits: int) -> None:
    """
    Aplica manualmente la Transformada Cuántica de Fourier inversa.

    La TCF inversa transforma la información almacenada en las fases
    de los cúbits en valores que pueden medirse en la base
    computacional.
    """

    # Invierte el orden de los cúbits mediante puertas SWAP.
    for qubit in range(numero_qubits // 2):
        circuito.swap(qubit,numero_qubits - qubit - 1)

    # Aplica las puertas de fase controladas inversas
    # y las puertas Hadamard.
    for objetivo in reversed(range(numero_qubits)):

        for control in reversed(
            range(objetivo + 1, numero_qubits)
        ):
            angulo = -pi / (2 ** (control - objetivo))

            circuito.cp(angulo,control,objetivo)

        circuito.h(objetivo)


def crear_circuito_shor_reducido(numero: int,base: int,periodo: int,numero_qubits: int) -> QuantumCircuit:
    """
    Construye una versión reducida del circuito de Shor.

    Parámetros:
        numero:
            Número compuesto que se desea factorizar.

        base:
            Valor a empleado en la función a^x mod N.

        periodo:
            Orden multiplicativo de a módulo N.

        numero_qubits:
            Número de cúbits del registro de control.

    La función conserva:
        - La superposición inicial.
        - La codificación de información periódica.
        - La TCF inversa.
        - La medición.

    No implementa la exponenciación modular reversible completa.
    """

    if gcd(base, numero) != 1:
        raise ValueError("La base elegida debe ser coprima con N.")

    circuito = QuantumCircuit(numero_qubits,numero_qubits)

    # 1. Preparación del registro en superposición.
    aplicar_superposicion(circuito,numero_qubits )
    circuito.barrier()

    # 2. Introducción artificial de la periodicidad.
    introducir_periodicidad(circuito,periodo,numero_qubits)

    circuito.barrier()

    # 3. Aplicación de la TCF inversa.
    aplicar_qft_inversa(circuito,numero_qubits)
    circuito.barrier()

    # 4. Medición del registro cuántico.
    circuito.measure(range(numero_qubits),range(numero_qubits))
    return circuito


# ============================================================
# POSPROCESADO CLÁSICO
# ============================================================

def obtener_factores(numero: int,base: int,periodo: int) -> tuple[int, int]:
    """
    Calcula los factores de N a partir del período obtenido.

    Shor utiliza:

        gcd(a^(r/2) - 1, N)
        gcd(a^(r/2) + 1, N)

    El período debe ser par y debe cumplirse:

        a^r mod N = 1
    """

    if periodo % 2 != 0:
        raise ValueError("El período debe ser par para obtener los factores.")

    if pow(base, periodo, numero) != 1:
        raise ValueError("El valor indicado no es un período válido.")

    potencia_intermedia = pow(base,periodo // 2,numero)

    factor_1 = gcd(potencia_intermedia - 1,numero)

    factor_2 = gcd(potencia_intermedia + 1,numero)

    if factor_1 in (1, numero) or factor_2 in (1, numero):
        raise ValueError(
            "El período no ha producido factores no triviales."
        )

    return factor_1, factor_2


# ============================================================
# PARÁMETROS PARA N = 221
# ============================================================

N = 221

# Se selecciona a = 2, que es coprimo con 221.
a = 2

# El orden multiplicativo de 2 módulo 221 es 24.
r = 24

# Se utilizan 12 cúbits para mejorar la precisión de la fase.
# La resolución del registro será 2^12 = 4096.
m = 12


# ============================================================
# CREACIÓN DEL CIRCUITO
# ============================================================

qc = crear_circuito_shor_reducido(numero=N,base=a,periodo=r,numero_qubits=m)

print("Circuito cuántico antes de la transpilación:")
print(qc.draw("text"))


# ============================================================
# CONEXIÓN CON IBM QUANTUM
# ============================================================

# Carga las credenciales guardadas previamente.
service = QiskitRuntimeService()

# Selecciona el backend operativo menos ocupado
# que disponga de al menos m cúbits físicos.
backend = service.least_busy(operational=True,simulator=False,min_num_qubits=m)

print("\nBackend seleccionado:", backend.name)


# ============================================================
# TRANSPILACIÓN
# ============================================================

# Adapta el circuito a las puertas nativas y a la conectividad
# del ordenador cuántico seleccionado.
gestor_transpilacion = generate_preset_pass_manager(backend=backend,optimization_level=3)

circuito_isa = gestor_transpilacion.run(qc)

print("Número de cúbits físicos del circuito transpiliado:",circuito_isa.num_qubits)

print("Profundidad tras la transpilación:",circuito_isa.depth())


# ============================================================
# EJECUCIÓN EN HARDWARE DE IBM
# ============================================================

sampler = Sampler(mode=backend)

trabajo = sampler.run([circuito_isa],shots=1024)

print("\nIdentificador del trabajo:", trabajo.job_id())

# Espera hasta que el trabajo termine.
resultado = trabajo.result()

# Obtiene la distribución de resultados de medida.
conteos = resultado[0].data.c.get_counts()

print("\nResultados de medida:")
print(conteos)

# Guardar los resultados en un archivo de texto
with open("Resultados.txt", "w", encoding="utf-8") as archivo:
    archivo.write("Resultados de medida\n")
    archivo.write("=====================\n\n")

    for estado, frecuencia in conteos.items():
        archivo.write(f"{estado}: {frecuencia}\n")

print("\nLos resultados se han guardado en 'Resultados.txt'.")

print("\nPeríodo utilizado:", r)
print("Factores obtenidos:", factor_1, "y", factor_2)
print("Comprobación:", factor_1,"*",factor_2,"=",factor_1 * factor_2
)
