"""Image check: Josev's EXI codec encodes and decodes on the packaged JVM.

Run inside the App image: python3 exi_roundtrip.py
"""
import json
import sys

sys.path.insert(0, "/opt/everest/libexec/everest/3rd_party/josev")
from iso15118.shared.exificient_exi_codec import ExificientEXICodec  # noqa: E402

CASES = (
    ({"supportedAppProtocolReq": {"AppProtocol": [{
        "ProtocolNamespace": "urn:iso:std:iso:15118:-20:DC", "VersionNumberMajor": 1,
        "VersionNumberMinor": 0, "SchemaID": 1, "Priority": 1}]}},
     "urn:iso:15118:2:2010:AppProtocol"),
    ({"SessionSetupReq": {"Header": {"SessionID": "00", "TimeStamp": 1791719386},
                          "EVCCID": "WMIV1234567890ABCDEX"}},
     "urn:iso:std:iso:15118:-20:CommonMessages"),
)

codec = ExificientEXICodec()
for message, namespace in CASES:
    exi = codec.encode(json.dumps(message), namespace)
    if json.loads(codec.decode(exi, namespace)) != message:
        sys.exit(f"EXI round trip changed {namespace}")
print(f"EXI codec {codec.get_version()}: {len(CASES)} round trips OK")
