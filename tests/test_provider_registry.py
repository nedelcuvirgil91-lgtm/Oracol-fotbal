"""Teste pentru provider_registry.py (ADR-034, PR1) — fără rețea, izolate de
starea reală a key_manager.py printr-un fake, urmând tiparul deja folosit în
test_football_providers.py (_FakeKeyManagerNoKey)."""
from __future__ import annotations

from acquisition_tier import AcquisitionTier
from provider_registry import ProviderRegistry, ProviderRecord, get_provider_registry


_FAKE_PROVIDERS = (
    ProviderRecord("alpha", "Alpha Provider", requires_credentials=True),
    ProviderRecord("beta", "Beta Provider (public)", requires_credentials=False),
)


class _FakeKeyManager:
    def __init__(self):
        self.recorded_requests: list[str] = []

    def is_available(self, provider_id):
        return provider_id == "alpha"  # doar alpha are "cheie" in fake

    def get_headers(self, provider_id):
        return {"x-api-key": "k1"} if provider_id == "alpha" else None

    def record_request(self, provider_id):
        self.recorded_requests.append(provider_id)

    def get_status(self):
        return {
            "month": "2026-07",
            "providers": {
                "alpha": {"name": "Alpha Provider", "keys": [
                    {"label": "Alpha-Key1", "used": 10, "limit": 100, "remaining": 90,
                     "pct": 10.0, "status": "ok", "icon": "🟢"},
                ], "status": "ok"},
            },
        }


def _registry() -> ProviderRegistry:
    return ProviderRegistry(key_manager=_FakeKeyManager(), providers=_FAKE_PROVIDERS)


def test_list_providers_is_domain_declaration_not_derived_from_key_manager():
    """Regresie centrala: Registry NU deriva din key_manager - e o declaratie
    proprie, independenta. Un provider fara credentiale (beta) apare normal,
    desi fake key_manager nu stie nimic despre el."""
    reg = _registry()
    ids = {r.provider_id for r in reg.list_providers()}
    assert ids == {"alpha", "beta"}


def test_get_provider_returns_none_for_unknown():
    reg = _registry()
    assert reg.get_provider("gamma-nu-exista") is None


def test_get_provider_returns_correct_record():
    reg = _registry()
    alpha = reg.get_provider("alpha")
    assert alpha == ProviderRecord("alpha", "Alpha Provider", requires_credentials=True)


def test_is_available_delegates_to_key_manager_only_when_credentials_required():
    reg = _registry()
    assert reg.is_available("alpha") is True   # delegat la fake key_manager


def test_is_available_true_for_keyless_provider_without_touching_key_manager():
    """beta nu necesita credentiale - trebuie sa fie mereu disponibil, fara
    sa consulte key_manager (fake-ul nici nu stie de 'beta')."""
    reg = _registry()
    assert reg.is_available("beta") is True


def test_is_available_false_for_unknown_provider():
    reg = _registry()
    assert reg.is_available("gamma-nu-exista") is False


def test_get_headers_delegates_only_for_credentialed_provider():
    reg = _registry()
    assert reg.get_headers("alpha") == {"x-api-key": "k1"}


def test_get_headers_none_for_keyless_provider():
    reg = _registry()
    assert reg.get_headers("beta") is None


def test_record_result_no_op_for_keyless_provider():
    """Providerii fara credentiale nu au concept de cota - record_result nu
    trebuie sa apeleze deloc key_manager pentru ei."""
    km = _FakeKeyManager()
    reg = ProviderRegistry(key_manager=km, providers=_FAKE_PROVIDERS)
    reg.record_result("beta", success=True)
    assert km.recorded_requests == []


def test_record_result_always_increments_quota_regardless_of_success():
    """Pentru providerii CU credentiale, cota se consuma indiferent de
    success - un provider real conteaza si apelurile esuate (404/429)."""
    km = _FakeKeyManager()
    reg = ProviderRegistry(key_manager=km, providers=_FAKE_PROVIDERS)
    reg.record_result("alpha", success=True)
    reg.record_result("alpha", success=False)
    assert km.recorded_requests == ["alpha", "alpha"]


def test_record_result_default_success_true():
    km = _FakeKeyManager()
    reg = ProviderRegistry(key_manager=km, providers=_FAKE_PROVIDERS)
    reg.record_result("alpha")
    assert km.recorded_requests == ["alpha"]


def test_get_quota_status_returns_provider_slice_for_credentialed_provider():
    reg = _registry()
    status = reg.get_quota_status("alpha")
    assert status["keys"][0]["remaining"] == 90


def test_get_quota_status_none_for_keyless_provider():
    reg = _registry()
    assert reg.get_quota_status("beta") is None


def test_get_quota_status_none_for_unknown_provider():
    reg = _registry()
    assert reg.get_quota_status("gamma-nu-exista") is None


def test_get_provider_registry_is_singleton():
    a = get_provider_registry()
    b = get_provider_registry()
    assert a is b


def test_real_registry_includes_keyless_providers():
    """Integrare reala (nu fake): confirma ca ESPN si TheSportsDB - surse
    active in fallback-ul din oracle_api.py azi, fara nicio cheie - apar in
    Registry, desi nu exista deloc in key_manager.PROVIDERS."""
    from key_manager import PROVIDERS as REAL_KEY_MANAGER_PROVIDERS
    reg = ProviderRegistry()
    ids = {r.provider_id for r in reg.list_providers()}
    assert "espn" in ids
    assert "thesportsdb" in ids
    assert "espn" not in REAL_KEY_MANAGER_PROVIDERS
    assert "thesportsdb" not in REAL_KEY_MANAGER_PROVIDERS


def test_key_manager_never_resolved_for_keyless_only_usage(monkeypatch):
    """TECH-DEBT-ADR034-001 (rezolvat in PR4): daca nu se injecteaza
    key_manager explicit si Registry-ul e folosit DOAR pentru provideri
    fara credentiale, get_key_manager() nu trebuie apelat niciodata -
    Registry-ul nu are voie sa atinga key_manager.py doar pentru ca a fost
    construit."""
    calls: list[None] = []

    def _spy_get_key_manager():
        calls.append(None)
        return _FakeKeyManager()

    monkeypatch.setattr("key_manager.get_key_manager", _spy_get_key_manager)

    reg = ProviderRegistry(providers=_FAKE_PROVIDERS)  # fara key_manager injectat
    assert reg.is_available("beta") is True
    assert reg.get_headers("beta") is None
    assert reg.record_result("beta") is None
    assert reg.get_quota_status("beta") is None
    assert calls == []


def test_key_manager_resolved_lazily_and_cached_for_credentialed_usage(monkeypatch):
    """Pentru un provider CU credentiale, get_key_manager() trebuie apelat -
    dar o singura data per instanta de Registry (cache dupa prima
    rezolvare), indiferent de cate metode operationale sunt apelate."""
    calls: list[None] = []
    fake = _FakeKeyManager()

    def _spy_get_key_manager():
        calls.append(None)
        return fake

    monkeypatch.setattr("key_manager.get_key_manager", _spy_get_key_manager)

    reg = ProviderRegistry(providers=_FAKE_PROVIDERS)  # fara key_manager injectat
    assert reg.is_available("alpha") is True
    assert reg.get_headers("alpha") == {"x-api-key": "k1"}
    reg.record_result("alpha")
    assert reg.get_quota_status("alpha") is not None
    assert len(calls) == 1  # rezolvat o singura data, apoi cache-uit


def test_key_manager_not_imported_at_module_load_time():
    """Regresie directa: provider_registry.py nu importa key_manager la
    nivel de modul - doar in interiorul _resolve_km(). Verificam ca numele
    'get_key_manager' nu exista in namespace-ul modulului la nivel de top."""
    import provider_registry
    assert "get_key_manager" not in vars(provider_registry)


def test_provider_record_defaults_to_api_tier():
    """[UDAL Faza 0, ADR-042] Aditiv — un ProviderRecord fara tier explicit
    ramane AcquisitionTier.API, zero schimbare de comportament pt cod
    existent."""
    record = ProviderRecord("alpha", "Alpha Provider", requires_credentials=True)
    assert record.tier is AcquisitionTier.API


def test_real_registry_all_providers_are_api_tier():
    """[UDAL Faza 0] Niciun provider din registry-ul real nu e azi un
    scraper sau target Playwright - toti raman AcquisitionTier.API."""
    reg = ProviderRegistry()
    for record in reg.list_providers():
        assert record.tier is AcquisitionTier.API, (
            f"{record.provider_id!r} nu e AcquisitionTier.API - regresie neasteptata"
        )


def test_real_registry_credentialed_providers_are_consistent_with_key_manager():
    """Toti providerii marcati requires_credentials=True in Registry
    TREBUIE sa aiba o intrare reala in key_manager.PROVIDERS - regresie
    directa impotriva desincronizarii, fara sa oblige Registry sa derive
    din key_manager (doar sa fie consistent cu el)."""
    from key_manager import PROVIDERS as REAL_KEY_MANAGER_PROVIDERS
    reg = ProviderRegistry()
    for record in reg.list_providers():
        if record.requires_credentials:
            assert record.provider_id in REAL_KEY_MANAGER_PROVIDERS, (
                f"{record.provider_id!r} marcat requires_credentials=True in "
                f"Registry, dar lipseste din key_manager.PROVIDERS"
            )
