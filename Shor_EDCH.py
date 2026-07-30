from math import pi

from qiskit import QuantumCircuit
from qiskit.transpiler import generate_preset_pass_manager
from qiskit_ibm_runtime import QiskitRuntimeService, SamplerV2

QiskitRuntimeService.save_account(
    channel="ibm_quantum",
    token="TU_API_KEY",
    overwrite=True
)

def aplicar_qft_inversa(circuito: QuantumCircuit, qubits: list[int]) -> None:
    """Aplica la Transformada Cuántica de Fourier inversa."""

    n = len(qubits)

    for i in range(n // 2):
        circuito.swap(qubits[i], qubits[n - i - 1])

    for objetivo in reversed(range(n)):
        for control in reversed(range(objetivo + 1, n)):
            angulo = -pi / 2 ** (control - objetivo)
            circuito.cp(angulo, qubits[control], qubits[objetivo])

        circuito.h(qubits[objetivo])


def introducir_fase(
    circuito: QuantumCircuit,
    qubits: list[int],
    numerador: int,
    orden: int
) -> None:
    """Codifica artificialmente la fase numerador/orden."""

    for posicion, qubit in enumerate(qubits):
        fase = 2 * pi * numerador * 2**posicion / orden
        circuito.p(fase, qubit)


def crear_circuito_ecdlp(
    orden: int,
    clave_privada: int,
    muestra_u: int,
    n: int
) -> QuantumCircuit:
    """
    Construye una versión reducida de Shor para el ECDLP.

    La función reversible f(x,y)=xG+yQ se sustituye por la
    introducción directa de fases relacionadas mediante
    v = ku mod orden.
    """

    muestra_v = clave_privada * muestra_u % orden
    total_qubits = 2 * n

    circuito = QuantumCircuit(total_qubits, total_qubits)

    registro_u = list(range(n))
    registro_v = list(range(n, total_qubits))

    circuito.h(range(total_qubits))
    circuito.barrier()

    introducir_fase(circuito, registro_u, muestra_u, orden)
    introducir_fase(circuito, registro_v, muestra_v, orden)

    circuito.barrier()

    aplicar_qft_inversa(circuito, registro_u)
    aplicar_qft_inversa(circuito, registro_v)

    circuito.barrier()

    circuito.measure(range(total_qubits), range(total_qubits))

    return circuito


# Curva: y² = x³ + 2x + 2 (mod 17)
# G = (5,1), Q = 7G = (0,6)

orden = 19
clave_privada = 7
muestra_u = 1

qubits_por_registro = 5
shots = 4096

circuito = crear_circuito_ecdlp(
    orden,
    clave_privada,
    muestra_u,
    qubits_por_registro
)

# Conexión con IBM Quantum
service = QiskitRuntimeService()

backend = service.least_busy(
    operational=True,
    simulator=False,
    min_num_qubits=2 * qubits_por_registro
)

pass_manager = generate_preset_pass_manager(
    backend=backend,
    optimization_level=3
)

circuito_isa = pass_manager.run(circuito)

sampler = SamplerV2(mode=backend)

trabajo = sampler.run(
    [circuito_isa],
    shots=shots
)

resultado = trabajo.result()

conteos = resultado[0].data.c.get_counts()

print(conteos)
