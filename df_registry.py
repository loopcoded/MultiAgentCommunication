# df_registry.py

from collections import defaultdict

# Structure:
# {
#   "service_type": {
#       "service_name": [
#           {"jid": "worker@localhost", "metadata": {...}},
#           ...
#       ]
#   }
# }
DF_REGISTRY = defaultdict(lambda: defaultdict(list))


def register_service(service_type, service_name, jid, metadata=None):
    """
    Registers an agent's service in the registry.
    """
    entry = {"jid": jid, "metadata": metadata or {}}

    # Prevent duplicate entries
    existing = DF_REGISTRY[service_type][service_name]
    if not any(e["jid"] == jid for e in existing):
        DF_REGISTRY[service_type][service_name].append(entry)
        print(f"[DF] Registered service: type='{service_type}', name='{service_name}', jid='{jid}'")


def search_service(service_type, service_name):
    """
    Searches for services of a given type and name.
    Returns a list of matching agent entries.
    """
    results = DF_REGISTRY[service_type].get(service_name, [])
    print(f"[DF] Search for service: type='{service_type}', name='{service_name}' → {len(results)} result(s)")
    return results
