"""Automatische Tests. Sie pruefen genau die Punkte, an denen das alte
System gescheitert ist: Race Conditions, halbe Schreibvorgaenge und
falsche Erledigt-Meldungen."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from robertos import agents, db, jobs, llm  # noqa: E402
from robertos.config import Config  # noqa: E402


def make_config(db_path: Path, dry_run: bool = False) -> Config:
    return Config(
        anthropic_api_key="test",
        telegram_bot_token="test",
        telegram_chat_id="42",
        model="claude-opus-5",
        effort="low",
        db_path=db_path,
        timezone="Europe/Berlin",
        dry_run=dry_run,
    )


def full_response(**overrides):
    data = {
        "telegram_message": "",
        "summary": "",
        "checkin_note": "",
        "state_updates": [],
        "handoffs": [],
        "processed_handoff_ids": [],
        "goal_updates": [],
        "metrics": [],
    }
    data.update(overrides)
    return data


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = db.init_db(Path(self.tmp.name) / "test.db")

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_transaktion_wird_bei_fehler_komplett_zurueckgerollt(self):
        with db.transaction(self.conn):
            db.set_state(self.conn, "robert_os_main", "fokus", "Angebot X")
        with self.assertRaises(RuntimeError):
            with db.transaction(self.conn):
                db.set_state(self.conn, "robert_os_main", "fokus", "Angebot Y")
                db.add_metric(self.conn, "robert_os_main", "calls", 3)
                raise RuntimeError("Absturz mitten im Schreiben")
        # Weder die Aenderung noch die Kennzahl duerfen existieren.
        self.assertEqual(db.get_states(self.conn, "robert_os_main")["fokus"], "Angebot X")
        self.assertEqual(len(db.recent_metrics(self.conn, "robert_os_main")), 0)

    def test_version_zaehlt_nur_bei_echter_aenderung(self):
        with db.transaction(self.conn):
            db.set_state(self.conn, "sales_main", "pipeline", "3 Angebote")
            db.set_state(self.conn, "sales_main", "pipeline", "3 Angebote")
            db.set_state(self.conn, "sales_main", "pipeline", "4 Angebote")
        row = self.conn.execute(
            "SELECT version FROM current_states WHERE agent='sales_main' AND key='pipeline'"
        ).fetchone()
        self.assertEqual(row["version"], 2)

    def test_fremde_uebergabe_kann_nicht_abgehakt_werden(self):
        with db.transaction(self.conn):
            handoff_id = db.add_handoff(
                self.conn, "sales_main", "performance_main", "t1", "info",
                "Fakt", "Entscheidung", "Naechster Schritt",
            )
        # Falscher Agent versucht abzuhaken
        with db.transaction(self.conn):
            self.assertFalse(db.close_handoff(self.conn, handoff_id, "robert_os_main"))
        # Richtiger Agent darf, aber nur einmal
        with db.transaction(self.conn):
            self.assertTrue(db.close_handoff(self.conn, handoff_id, "performance_main"))
        with db.transaction(self.conn):
            self.assertFalse(db.close_handoff(self.conn, handoff_id, "performance_main"))

    def test_ziel_wird_aktualisiert_statt_doppelt_angelegt(self):
        with db.transaction(self.conn):
            first = db.upsert_goal(self.conn, "sales_main", "Website fertig", "open")
            second = db.upsert_goal(self.conn, "sales_main", "Website fertig", "done")
        self.assertEqual(first, second)
        self.assertEqual(len(db.open_goals(self.conn, "sales_main")), 0)


class AgentRunTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "test.db"
        self.conn = db.init_db(self.db_path)
        self.config = make_config(self.db_path)
        self.sent: list[str] = []

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def fake_ask(self, response):
        def _ask(**kwargs):
            self.last_prompt = kwargs["user"]
            return llm.LLMResult(data=response, input_tokens=100, output_tokens=50,
                                 model="claude-opus-5")
        return _ask

    def notify(self, text):
        self.sent.append(text)
        return 1

    def test_kompletter_lauf_schreibt_alles_und_meldet_sich(self):
        response = full_response(
            telegram_message="Heute drei Dinge: Angebot raus, Anruf Meier, Sport.",
            summary="Tag geplant",
            checkin_note="Plan steht",
            state_updates=[{"key": "tagesprioritaeten", "value": "Angebot, Anruf, Sport"}],
            handoffs=[{
                "target_agent": "sales_main", "thread_key": "meier",
                "type": "aufgabe", "facts": "Meier hat seit 8 Tagen nicht geantwortet",
                "decision": "Nachfassen", "next_step": "Heute anrufen",
            }],
            goal_updates=[{"title": "Angebot Meier", "status": "active",
                           "due": "2026-09-10", "detail": ""}],
            metrics=[{"metric": "geplante_aufgaben", "value": 3, "note": ""}],
        )
        run = agents.run_agent(
            self.conn, self.config, "robert_os_main", "Morgensteuerung",
            ask=self.fake_ask(response), notify=self.notify,
        )
        self.assertTrue(run.ok, run.error)
        self.assertTrue(run.telegram_sent)
        self.assertEqual(len(self.sent), 1)
        self.assertIn("Angebot raus", self.sent[0])
        self.assertEqual(
            db.get_states(self.conn, "robert_os_main")["tagesprioritaeten"],
            "Angebot, Anruf, Sport",
        )
        self.assertEqual(len(db.open_handoffs(self.conn, "sales_main")), 1)
        self.assertEqual(len(db.open_goals(self.conn, "robert_os_main")), 1)
        self.assertEqual(len(db.recent_metrics(self.conn, "robert_os_main")), 1)
        # Historie und Protokoll wurden mitgeschrieben
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) c FROM state_history").fetchone()["c"], 1)
        self.assertEqual(
            self.conn.execute(
                "SELECT result FROM execution_log ORDER BY id DESC LIMIT 1"
            ).fetchone()["result"], "ok")

    def test_agent_kann_fremde_uebergabe_nicht_als_erledigt_melden(self):
        with db.transaction(self.conn):
            fremde_id = db.add_handoff(
                self.conn, "sales_main", "performance_main", "t", "info",
                "f", "d", "n")
        response = full_response(processed_handoff_ids=[fremde_id, 9999])
        run = agents.run_agent(
            self.conn, self.config, "robert_os_main", "Test",
            ask=self.fake_ask(response), notify=self.notify)
        self.assertTrue(run.ok)
        self.assertEqual(run.applied["Uebergaben abgeschlossen"], 0)
        self.assertEqual(len(db.open_handoffs(self.conn, "performance_main")), 1)

    def test_eigene_uebergabe_wird_korrekt_abgeschlossen(self):
        with db.transaction(self.conn):
            eigene_id = db.add_handoff(
                self.conn, "sales_main", "robert_os_main", "t", "info",
                "f", "d", "n")
        response = full_response(processed_handoff_ids=[eigene_id], summary="erledigt")
        run = agents.run_agent(
            self.conn, self.config, "robert_os_main", "Test",
            ask=self.fake_ask(response), notify=self.notify)
        self.assertEqual(run.applied["Uebergaben abgeschlossen"], 1)
        self.assertEqual(len(db.open_handoffs(self.conn, "robert_os_main")), 0)

    def test_fehler_der_ki_wird_protokolliert_statt_verschwiegen(self):
        def kaputt(**kwargs):
            raise llm.LLMError("Schnittstelle nicht erreichbar")
        run = agents.run_agent(
            self.conn, self.config, "robert_os_main", "Test",
            ask=kaputt, notify=self.notify)
        self.assertFalse(run.ok)
        self.assertIn("nicht erreichbar", run.error)
        self.assertEqual(self.sent, [])
        row = self.conn.execute(
            "SELECT result FROM execution_log ORDER BY id DESC LIMIT 1").fetchone()
        self.assertEqual(row["result"], "fehler")

    def test_telegram_ausfall_verfaelscht_die_daten_nicht(self):
        def kaputter_versand(text):
            raise RuntimeError("Handy nicht erreichbar")
        response = full_response(
            telegram_message="Wichtige Meldung",
            state_updates=[{"key": "fokus", "value": "Angebot"}])
        run = agents.run_agent(
            self.conn, self.config, "robert_os_main", "Test",
            ask=self.fake_ask(response), notify=kaputter_versand)
        self.assertTrue(run.ok)
        self.assertFalse(run.telegram_sent)
        self.assertIn("Telegram-Versand fehlgeschlagen", run.error)
        # Die Daten sind trotzdem sauber gespeichert.
        self.assertEqual(db.get_states(self.conn, "robert_os_main")["fokus"], "Angebot")
        results = [r["result"] for r in self.conn.execute(
            "SELECT result FROM execution_log ORDER BY id").fetchall()]
        self.assertEqual(results, ["ok", "telegram_fehler"])

    def test_posteingang_landet_im_kontext_und_wird_danach_abgehakt(self):
        with db.transaction(self.conn):
            db.add_inbox(self.conn, "telegram", "Termin mit Meier verschoben")
        run = agents.run_agent(
            self.conn, self.config, "robert_os_main", "Test",
            ask=self.fake_ask(full_response()), notify=self.notify)
        self.assertTrue(run.ok)
        self.assertIn("Termin mit Meier verschoben", self.last_prompt)
        self.assertEqual(len(db.unread_inbox(self.conn)), 0)

    def test_ohne_nachricht_wird_nichts_gesendet(self):
        run = agents.run_agent(
            self.conn, self.config, "robert_os_main", "Test",
            ask=self.fake_ask(full_response(summary="nichts Neues")),
            notify=self.notify)
        self.assertTrue(run.ok)
        self.assertEqual(self.sent, [])

    def test_job_laesst_agenten_in_der_richtigen_reihenfolge_laufen(self):
        runs = jobs.run_job(
            self.conn, self.config, "abend",
            ask=self.fake_ask(full_response(summary="ok")), notify=self.notify)
        self.assertEqual(
            [r.agent for r in runs],
            ["sales_main", "performance_main", "robert_os_main"])
        self.assertTrue(all(r.ok for r in runs))

    def test_uebergabe_aus_demselben_job_ist_fuer_den_naechsten_sichtbar(self):
        antworten = {
            "sales_main": full_response(handoffs=[{
                "target_agent": "robert_os_main", "thread_key": "meier",
                "type": "eskalation", "facts": "Kunde wartet",
                "decision": "Robert entscheidet", "next_step": "Rueckruf heute"}]),
            "performance_main": full_response(),
            "robert_os_main": full_response(summary="gesehen"),
        }
        gesehen = {}

        def ask(**kwargs):
            # Agent anhand des Kontexttextes bestimmen
            for name, label in (("sales_main", "Sales Main"),
                                ("performance_main", "Performance Main"),
                                ("robert_os_main", "Robert-OS Main")):
                if f"DEIN NAME: {label}" in kwargs["user"]:
                    gesehen[name] = kwargs["user"]
                    return llm.LLMResult(data=antworten[name], model="claude-opus-5")
            raise AssertionError("Agent nicht erkannt")

        jobs.run_job(self.conn, self.config, "abend", ask=ask, notify=self.notify)
        self.assertIn("Rueckruf heute", gesehen["robert_os_main"])


class ParallelTests(unittest.TestCase):
    """Beweist, dass zwei gleichzeitig schreibende Agenten sich nicht
    gegenseitig ueberschreiben - der Kernfehler des alten Systems."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "test.db"
        db.init_db(self.db_path).close()

    def tearDown(self):
        self.tmp.cleanup()

    def test_gleichzeitige_schreibzugriffe_gehen_nicht_verloren(self):
        import threading

        fehler: list[Exception] = []

        def hochzaehlen(runden: int):
            conn = db.connect(self.db_path)
            try:
                for _ in range(runden):
                    with db.transaction(conn):
                        row = conn.execute(
                            "SELECT value FROM current_states "
                            "WHERE agent='shared' AND key='zaehler'").fetchone()
                        alt = int(row["value"]) if row else 0
                        db.set_state(conn, "shared", "zaehler", str(alt + 1))
            except Exception as exc:  # pragma: no cover
                fehler.append(exc)
            finally:
                conn.close()

        threads = [threading.Thread(target=hochzaehlen, args=(25,)) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(fehler, [])
        conn = db.connect(self.db_path)
        row = conn.execute(
            "SELECT value, version FROM current_states "
            "WHERE agent='shared' AND key='zaehler'").fetchone()
        conn.close()
        # 4 Threads x 25 Runden = 100. Kein einziger Zaehlschritt darf fehlen.
        self.assertEqual(int(row["value"]), 100)
        self.assertEqual(row["version"], 100)


class EnvDateiTests(unittest.TestCase):
    """Der Einrichtungs-Assistent schreibt die Zugangsdaten. Dabei darf er
    nichts anderes in der Datei kaputt machen."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / ".env"

    def tearDown(self):
        self.tmp.cleanup()

    def test_werte_werden_eingetragen_und_datei_ist_geschuetzt(self):
        from robertos.config import write_env_values

        write_env_values({"ANTHROPIC_API_KEY": "sk-ant-eins"}, self.path)
        inhalt = self.path.read_text()
        self.assertIn("ANTHROPIC_API_KEY=sk-ant-eins", inhalt)
        # Die Vorlage bringt die uebrigen Einstellungen mit.
        self.assertIn("ROBERTOS_MODEL=", inhalt)
        self.assertEqual(oct(self.path.stat().st_mode)[-3:], "600")

    def test_zweiter_durchlauf_ueberschreibt_nur_den_neuen_wert(self):
        from robertos.config import write_env_values

        write_env_values({"ANTHROPIC_API_KEY": "sk-ant-eins",
                          "TELEGRAM_CHAT_ID": "111"}, self.path)
        write_env_values({"TELEGRAM_CHAT_ID": "222"}, self.path)
        zeilen = self.path.read_text().splitlines()
        self.assertIn("ANTHROPIC_API_KEY=sk-ant-eins", zeilen)
        self.assertIn("TELEGRAM_CHAT_ID=222", zeilen)
        self.assertNotIn("TELEGRAM_CHAT_ID=111", zeilen)
        # Jeder Schluessel steht genau einmal drin.
        self.assertEqual(
            sum(1 for z in zeilen if z.startswith("TELEGRAM_CHAT_ID=")), 1)

    def test_kommentare_bleiben_erhalten(self):
        from robertos.config import write_env_values

        self.path.write_text("# meine Notiz\nANTHROPIC_API_KEY=alt\n")
        write_env_values({"ANTHROPIC_API_KEY": "neu"}, self.path)
        inhalt = self.path.read_text()
        self.assertIn("# meine Notiz", inhalt)
        self.assertIn("ANTHROPIC_API_KEY=neu", inhalt)


class PromptTests(unittest.TestCase):
    def test_alle_vier_rollentexte_sind_vorhanden(self):
        from robertos.config import AGENTS
        for agent in AGENTS:
            text = agents.load_system_prompt(agent)
            self.assertIn("Gemeinsame Regeln", text)
            self.assertGreater(len(text), 500)


if __name__ == "__main__":
    unittest.main(verbosity=2)
