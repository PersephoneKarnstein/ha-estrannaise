"""End-to-end tests for the standalone API, against a real temp SQLite file."""

from __future__ import annotations

import importlib
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """A TestClient with an isolated data directory."""
    monkeypatch.setenv("ESTRANNAISE_DATA", str(tmp_path))
    monkeypatch.setenv("TZ", "America/Vancouver")
    monkeypatch.setenv("ESTRANNAISE_FRAME_ANCESTORS", "http://homarr.example")

    for name in [m for m in sys.modules if m.startswith("standalone.")]:
        del sys.modules[name]
    app_module = importlib.import_module("standalone.app")
    importlib.reload(app_module)

    from fastapi.testclient import TestClient

    with TestClient(app_module.app) as c:
        yield c


REGIMEN = {
    "ester": "EEn",
    "method": "im",
    "dose_mg": 4.0,
    "interval_days": 7.0,
    "mode": "manual",
    "dose_time": "08:00",
}


def configure(client, **overrides):
    payload = {"units": "pg/mL", "regimens": [{**REGIMEN, **overrides}]}
    r = client.post("/api/config", json=payload)
    assert r.status_code == 200, r.text
    return r.json()["regimens"][0]["entry_id"]


class TestHealth:
    def test_healthz(self, client):
        assert client.get("/healthz").json() == {"ok": True}


class TestSecurityHeaders:
    def test_frame_ancestors_allows_configured_origin(self, client):
        csp = client.get("/healthz").headers["content-security-policy"]
        assert "frame-ancestors 'self' http://homarr.example" == csp

    def test_no_cors_header_is_emitted(self, client):
        # An explicit non-goal: cross-origin reads of medical data.
        assert "access-control-allow-origin" not in client.get("/healthz").headers

    def test_nosniff(self, client):
        assert client.get("/healthz").headers["x-content-type-options"] == "nosniff"


class TestConfig:
    def test_starts_with_no_regimens(self, client):
        assert client.get("/api/config").json()["regimens"] == []

    def test_save_assigns_entry_id(self, client):
        entry_id = configure(client)
        assert entry_id

    def test_config_round_trips(self, client):
        configure(client, dose_mg=6.0)
        assert client.get("/api/config").json()["regimens"][0]["dose_mg"] == 6.0

    def test_entry_id_is_stable_across_saves(self, client):
        first = configure(client)
        cfg = client.get("/api/config").json()
        cfg["regimens"][0]["dose_mg"] = 5.0
        client.post("/api/config", json=cfg)
        assert client.get("/api/config").json()["regimens"][0]["entry_id"] == first

    def test_corrupt_config_is_not_silently_reset(self, client, tmp_path):
        configure(client)
        (tmp_path / "config.json").write_text("{ this is not json")
        r = client.get("/api/config")
        assert r.status_code == 500
        assert "Refusing to start with default settings" in r.json()["detail"]

    def test_config_write_is_atomic(self, client, tmp_path):
        configure(client)
        leftovers = list(tmp_path.glob(".config-*.tmp"))
        assert leftovers == []


class TestRegimenValidation:
    def test_rejects_unsupported_combination(self, client):
        r = client.post("/api/config", json={
            "units": "pg/mL",
            "regimens": [{**REGIMEN, "ester": "EEn", "method": "patch"}],
        })
        assert r.status_code == 400
        # The error must say what IS allowed, not just that this is not.
        assert "Intramuscular" in r.json()["detail"]

    def test_rejects_oral_injectable(self, client):
        r = client.post("/api/config", json={
            "units": "pg/mL",
            "regimens": [{**REGIMEN, "ester": "E", "method": "im"}],
        })
        assert r.status_code == 400

    def test_accepts_patch_for_plain_estradiol(self, client):
        r = client.post("/api/config", json={
            "units": "pg/mL",
            "regimens": [{**REGIMEN, "ester": "E", "method": "patch",
                          "interval_days": 3.5}],
        })
        assert r.status_code == 200

    def test_state_advertises_supported_methods(self, client):
        configure(client)
        supported = client.get("/api/state").json()["supported_methods"]
        assert supported["EEn"] == ["im", "subq"]
        assert supported["E"] == ["patch", "oral"]


class TestDoses:
    def test_log_and_list(self, client):
        entry_id = configure(client)
        r = client.post("/api/doses", json={"entry_id": entry_id, "dose_mg": 4.0})
        assert r.status_code == 200
        assert r.json()["model"]
        assert len(client.get("/api/state").json()["doses"]) == 1

    def test_model_is_resolved_from_regimen(self, client):
        entry_id = configure(client)
        r = client.post("/api/doses", json={"entry_id": entry_id, "dose_mg": 4.0})
        assert r.json()["model"] == "EEn im"

    def test_rejects_nonpositive_dose(self, client):
        entry_id = configure(client)
        r = client.post("/api/doses", json={"entry_id": entry_id, "dose_mg": 0})
        assert r.status_code == 422

    def test_rejects_unknown_model(self, client):
        entry_id = configure(client)
        r = client.post(
            "/api/doses",
            json={"entry_id": entry_id, "dose_mg": 4.0, "model": "not a model"},
        )
        assert r.status_code == 400

    def test_rejects_unknown_entry(self, client):
        configure(client)
        r = client.post("/api/doses", json={"entry_id": "nope", "dose_mg": 4.0})
        assert r.status_code == 404

    def test_requires_a_regimen(self, client):
        r = client.post("/api/doses", json={"dose_mg": 4.0})
        assert r.status_code == 400
        assert "No regimen configured" in r.json()["detail"]

    def test_delete(self, client):
        entry_id = configure(client)
        dose_id = client.post(
            "/api/doses", json={"entry_id": entry_id, "dose_mg": 4.0}
        ).json()["id"]
        assert (
            client.delete(f"/api/doses/{dose_id}?entry_id={entry_id}").status_code == 200
        )
        assert client.get("/api/state").json()["doses"] == []

    def test_delete_missing_is_404(self, client):
        entry_id = configure(client)
        assert (
            client.delete(f"/api/doses/99999?entry_id={entry_id}").status_code == 404
        )


class TestBloodTests:
    def test_log_and_affects_calibration(self, client):
        entry_id = configure(client)
        client.post("/api/doses", json={"entry_id": entry_id, "dose_mg": 4.0})
        client.post(
            "/api/blood-tests",
            json={"entry_id": entry_id, "level_pg_ml": 150.0, "on_schedule": True},
        )
        state = client.get("/api/state").json()
        assert len(state["blood_tests"]) == 1
        assert state["scaling_factor"] != 1.0

    def test_rejects_negative_level(self, client):
        entry_id = configure(client)
        r = client.post(
            "/api/blood-tests", json={"entry_id": entry_id, "level_pg_ml": -1}
        )
        assert r.status_code == 422


class TestState:
    def test_shape(self, client):
        configure(client)
        state = client.get("/api/state").json()
        for key in (
            "current_e2", "units", "doses", "blood_tests", "scaling_factor",
            "users", "all_configs", "target_range", "pk_parameters",
        ):
            assert key in state

    def test_current_e2_rises_after_a_dose(self, client):
        # Dated two days back: an IM enanthate depot is still ~0 pg/mL at the
        # moment of injection and takes days to rise, so a dose logged "now"
        # correctly leaves the current level unchanged.
        entry_id = configure(client)
        before = client.get("/api/state").json()["current_e2"]
        client.post(
            "/api/doses",
            json={
                "entry_id": entry_id,
                "dose_mg": 4.0,
                "timestamp": time.time() - 2 * 86400,
            },
        )
        assert client.get("/api/state").json()["current_e2"] > before

    def test_dose_logged_now_has_not_absorbed_yet(self, client):
        entry_id = configure(client)
        client.post("/api/doses", json={"entry_id": entry_id, "dose_mg": 4.0})
        assert client.get("/api/state").json()["current_e2"] == 0.0

    def test_automatic_mode_backfills(self, client):
        configure(client, mode="automatic", backfill_doses=True)
        assert len(client.get("/api/state").json()["doses"]) >= 10

    def test_manual_mode_does_not_backfill(self, client):
        configure(client, mode="manual", backfill_doses=True)
        assert client.get("/api/state").json()["doses"] == []

    def test_automatic_mode_projects_future_doses(self, client):
        configure(client, mode="automatic")
        assert client.get("/api/state").json()["auto_doses"]


class TestHistoryRetention:
    """History must survive. build_state used to prune on every request."""

    def test_old_doses_are_not_deleted(self, client):
        entry_id = configure(client)
        # Well past any PK model's terminal elimination window.
        ancient = time.time() - 400 * 86400
        client.post("/api/doses", json={"entry_id": entry_id, "dose_mg": 4.0,
                                        "timestamp": ancient})
        # Several state builds, as a dashboard polling would produce.
        for _ in range(3):
            client.get("/api/state")
        doses = client.get("/api/state").json()["doses"]
        assert len(doses) == 1, "an imported historical dose was deleted"
        assert doses[0]["timestamp"] == pytest.approx(ancient, abs=1)

    def test_old_blood_tests_are_not_deleted(self, client):
        entry_id = configure(client)
        ancient = time.time() - 400 * 86400
        client.post("/api/blood-tests", json={"entry_id": entry_id,
                                              "level_pg_ml": 120.0,
                                              "timestamp": ancient,
                                              "on_schedule": True})
        for _ in range(3):
            client.get("/api/state")
        assert len(client.get("/api/state").json()["blood_tests"]) == 1


class TestCurve:
    def test_sample_count_and_units(self, client):
        configure(client)
        d = client.get("/api/curve?days_back=10&days_forward=10&points=50").json()
        assert len(d["series"][0]["samples"]) == 50
        assert d["units"] == "pg/mL"

    def test_points_are_clamped(self, client):
        configure(client)
        d = client.get("/api/curve?points=99999").json()
        assert len(d["series"][0]["samples"]) == 2000

    def test_pmol_conversion_scales_the_curve(self, client):
        entry_id = configure(client)
        client.post("/api/doses", json={"entry_id": entry_id, "dose_mg": 4.0})
        pg = max(p["e2"] for p in client.get("/api/curve").json()["series"][0]["samples"])
        cfg = client.get("/api/config").json()
        cfg["units"] = "pmol/L"
        client.post("/api/config", json=cfg)
        pmol = max(
            p["e2"] for p in client.get("/api/curve").json()["series"][0]["samples"]
        )
        assert pmol == pytest.approx(pg * 3.6713, rel=0.01)


class TestClearData:
    def test_refuses_without_confirmation(self, client):
        configure(client)
        assert client.delete("/api/data").status_code == 400

    def test_clears_with_confirmation(self, client):
        entry_id = configure(client)
        client.post("/api/doses", json={"entry_id": entry_id, "dose_mg": 4.0})
        assert client.delete("/api/data?confirm=DELETE").status_code == 200
        assert client.get("/api/state").json()["doses"] == []


@pytest.fixture()
def secured(tmp_path, monkeypatch):
    """A client with token auth switched on."""
    monkeypatch.setenv("ESTRANNAISE_DATA", str(tmp_path))
    monkeypatch.setenv("TZ", "America/Vancouver")
    monkeypatch.setenv("ESTRANNAISE_TOKEN", "s3cret-token")

    for name in [m for m in sys.modules if m.startswith("standalone.")]:
        del sys.modules[name]
    app_module = importlib.import_module("standalone.app")
    importlib.reload(app_module)

    from fastapi.testclient import TestClient

    with TestClient(app_module.app) as c:
        yield c


class TestTokenAuth:
    def test_api_rejects_missing_token(self, secured):
        assert secured.get("/api/state").status_code == 401

    def test_api_rejects_wrong_token(self, secured):
        r = secured.get("/api/state", headers={"X-Estrannaise-Token": "nope"})
        assert r.status_code == 401

    def test_header_token_accepted(self, secured):
        r = secured.get("/api/state", headers={"X-Estrannaise-Token": "s3cret-token"})
        assert r.status_code == 200

    def test_query_token_accepted(self, secured):
        assert secured.get("/api/state?token=s3cret-token").status_code == 200

    def test_query_token_sets_cookie_for_later_bare_requests(self, secured):
        secured.get("/api/state?token=s3cret-token")
        assert secured.cookies.get("estrannaise_token") == "s3cret-token"
        assert secured.get("/api/state").status_code == 200

    def test_writes_are_protected(self, secured):
        assert secured.post("/api/doses", json={"dose_mg": 4.0}).status_code == 401

    def test_clear_data_is_protected(self, secured):
        assert secured.delete("/api/data?confirm=DELETE").status_code == 401

    def test_embeds_are_protected(self, secured):
        assert secured.get("/embed/level").status_code == 401

    def test_embed_carries_token_to_its_own_fetches(self, secured):
        # The page must hold the token inline: a cross-origin iframe gets no cookie.
        body = secured.get("/embed/level?token=s3cret-token").text
        assert "s3cret-token" in body
        assert "X-Estrannaise-Token" in body

    def test_healthz_stays_open_for_the_docker_healthcheck(self, secured):
        assert secured.get("/healthz").status_code == 200

    def test_static_assets_stay_open(self, secured):
        # Carries no personal data, and the embeds need Plotly before authing.
        assert secured.get("/static/nonexistent.js").status_code == 404

    def test_no_auth_when_token_unset(self, client):
        assert client.get("/api/state").status_code == 200

    def test_page_gets_no_token_when_auth_disabled(self, client):
        assert '__ESTRANNAISE_TOKEN__ = ""' in client.get("/embed/level").text


class TestEmbeds:
    @pytest.mark.parametrize("path", ["/embed/plot", "/embed/buttons", "/embed/level"])
    def test_render_html(self, client, path):
        r = client.get(path)
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/html")
        assert "<!DOCTYPE html>" in r.text

    @pytest.mark.parametrize("path", ["/embed/plot", "/embed/buttons", "/embed/level"])
    def test_embeddable_by_configured_origin(self, client, path):
        assert "http://homarr.example" in client.get(path).headers[
            "content-security-policy"
        ]

    def test_light_theme_switches_class(self, client):
        assert 'class="light"' in client.get("/embed/level?theme=light").text

    def test_theme_defaults_to_dark(self, client):
        assert 'class="dark"' in client.get("/embed/level").text

    def test_unknown_theme_falls_back_to_dark(self, client):
        assert 'class="dark"' in client.get("/embed/level?theme=nonsense").text
