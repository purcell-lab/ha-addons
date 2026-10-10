"""Small, fail-closed downstream adaptations of an exactly pinned upstream tree."""
import gzip
import subprocess
import sys
from pathlib import Path

REVISION = "2cb07cdbe53954a694a29336ab31eac2d2b48673"


def replace_once(path, old, new, count=1):
    text = path.read_text()
    if text.count(old) != count:
        raise ValueError(f"upstream context changed: {path.name}")
    path.write_text(text.replace(old, new, count))


def prepare(root):
    revision = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
    ).strip()
    if revision != REVISION:
        raise ValueError("unreviewed upstream revision")
    cmake = root / "CMakeLists.txt"
    # Retain upstream 2.0.1 compilation and select it unconditionally below.
    replace_once(cmake, "    MO_TRAFFIC_OUT\n", "")
    replace_once(cmake, "MO_DBG_LEVEL=MO_DL_INFO", "MO_DBG_LEVEL=MO_DL_WARN")
    main = root / "src/main.cpp"
    start = main.read_text().index("void load_ocpp_version(")
    end = main.read_text().index("\nvoid app_setup(", start)
    main.write_text(main.read_text()[:start] +
                    "void load_ocpp_version(std::shared_ptr<MicroOcpp::FilesystemAdapter>) {\n"
                    "    g_isOcpp201 = true;\n}\n" + main.read_text()[end:])
    replace_once(main, '"http://0.0.0.0:8000"', '"http://127.0.0.1:8000"')
    replace_once(main, '"ws://echo.websocket.events"', '""')
    replace_once(main, '"charger-01"', '"SIM-MICROOCPP-01"')
    replace_once(main, "mg_log_set(MG_LL_INFO)", "mg_log_set(MG_LL_ERROR)")
    replace_once(main, "sigaction(SIGINT, &sigIntHandler, NULL);",
                 "sigaction(SIGINT, &sigIntHandler, NULL);\n"
                 "    sigaction(SIGTERM, &sigIntHandler, NULL);")
    # Keep CSMS ChangeConfiguration from changing the network identity.
    client = root / "lib/MicroOcppMongoose/src/MicroOcppMongooseClient.cpp"
    replace_once(client, "readonly = false;", "readonly = true;")
    for variable in ("csmsUrl", "identity", "basicAuthPassword"):
        replace_once(client, f"{variable}->setPersistent();",
                     f"{variable}->setPersistent();\n"
                     f"        {variable}->setMutability(Variable::Mutability::ReadOnly);")
    # The original HTTP API returns the legacy integer ID (-1 in 2.x).
    replace_once(root / "src/evse.h", "int getTransactionId();",
                 "const char *getTransactionId();")
    replace_once(root / "src/evse.cpp",
                 "int Evse::getTransactionId() {\n"
                 "    return getTransaction(connectorId) ? getTransaction(connectorId)->getTransactionId() : -1;\n}",
                 "const char *Evse::getTransactionId() {\n"
                 "    auto service = getOcppContext()->getModel().getTransactionService();\n"
                 "    auto evse = service ? service->getEvse(connectorId) : nullptr;\n"
                 "    auto tx = evse ? evse->getTransaction() : nullptr;\n"
                 '    return tx ? tx->transactionId : "";\n}')
    # Upstream 2.x defaults send no sampled data. Provide useful lab defaults.
    metering = root / "lib/MicroOcpp/src/MicroOcpp/Model/Metering/MeterValuesV201.cpp"
    for name in ("TxStartedMeasurands", "TxUpdatedMeasurands", "TxEndedMeasurands"):
        replace_once(metering, f'"SampledDataCtrlr", "{name}", ""',
                     f'"SampledDataCtrlr", "{name}", '
                     '"Energy.Active.Import.Register,Power.Active.Import,Current.Import,Voltage,SoC"', count=2)
    replace_once(root / "lib/MicroOcpp/src/MicroOcpp/Model/Transactions/TransactionService.cpp",
                 '"SampledDataCtrlr", "TxUpdatedInterval", 0',
                 '"SampledDataCtrlr", "TxUpdatedInterval", 10')
    bundle = root / "public/bundle.html.gz"
    text = gzip.decompress(bundle.read_bytes()).decode()
    old = '"http://localhost:8000/api"'
    if text.count(old) != 1:
        raise ValueError("upstream UI API-root context changed")
    text = text.replace(old, 'new URL("api",window.location.href).href')
    bundle.write_bytes(gzip.compress(text.encode(), mtime=0))


if __name__ == "__main__":
    prepare(Path(sys.argv[1]).resolve())
