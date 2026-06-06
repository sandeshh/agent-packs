import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "cli" / "bin" / "agent-packs"


class InstallCommandTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        subprocess.run(
            ["go", "build", "-o", "bin/agent-packs", "./cmd/agent-packs"],
            cwd=ROOT / "cli",
            check=True,
            text=True,
            capture_output=True,
        )

    def run_cli(self, *args, registry, target):
        env = os.environ.copy()
        env["AGENT_PACKS_REGISTRY"] = str(registry)
        return subprocess.run(
            [str(CLI), *args, "--target", str(target)],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
        )

    def write_pack(self, registry, pack):
        path = registry / f"{pack['id']}.json"
        path.write_text(json.dumps(pack, indent=2) + "\n", encoding="utf-8")
        return path

    def test_dry_run_prints_skill_and_plugin_plan_without_writing_receipt(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            registry = temp / "registry"
            target = temp / "install"
            registry.mkdir()
            self.write_pack(registry, example_pack(temp / "skill"))

            result = self.run_cli("install", "example", "--dry-run", registry=registry, target=target)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Pack: example", result.stdout)
            self.assertIn("plugin: Example plugin", result.stdout)
            self.assertIn("command: echo install-plugin", result.stdout)
            self.assertFalse((target / "receipts" / "example.json").exists())

    def test_installs_local_skill_and_writes_receipt(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            skill = temp / "skill"
            skill.mkdir()
            (skill / "SKILL.md").write_text("# Example Skill\n", encoding="utf-8")
            registry = temp / "registry"
            target = temp / "install"
            registry.mkdir()
            self.write_pack(registry, example_pack(skill))

            result = self.run_cli("install", "example", "--agent", "codex", "--only", "skills", "--mode", "copy", registry=registry, target=target)

            self.assertEqual(result.returncode, 0, result.stderr)
            installed_skill = target / ".codex" / "skills" / "example-skill" / "SKILL.md"
            self.assertEqual(installed_skill.read_text(encoding="utf-8"), "# Example Skill\n")

            receipt = json.loads((target / "receipts" / "example.json").read_text(encoding="utf-8"))
            self.assertEqual(receipt["plan"]["agent"], "codex")
            self.assertEqual(receipt["plan"]["capabilities"][0]["status"], "installed")

    def test_installs_multiple_packs_and_writes_individual_receipts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            first_skill = temp / "first-skill"
            second_skill = temp / "second-skill"
            first_skill.mkdir()
            second_skill.mkdir()
            (first_skill / "SKILL.md").write_text("# First Skill\n", encoding="utf-8")
            (second_skill / "SKILL.md").write_text("# Second Skill\n", encoding="utf-8")
            registry = temp / "registry"
            target = temp / "install"
            registry.mkdir()
            self.write_pack(registry, skill_only_pack("first", "First Skill", first_skill))
            self.write_pack(registry, skill_only_pack("second", "Second Skill", second_skill))

            result = self.run_cli("install", "first", "second", "--agent", "codex", "--only", "skills", "--mode", "copy", registry=registry, target=target)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("==> Installing first (1/2)", result.stdout)
            self.assertIn("==> Installing second (2/2)", result.stdout)
            self.assertTrue((target / "receipts" / "first.json").exists())
            self.assertTrue((target / "receipts" / "second.json").exists())
            self.assertEqual((target / ".codex" / "skills" / "first-skill" / "SKILL.md").read_text(encoding="utf-8"), "# First Skill\n")
            self.assertEqual((target / ".codex" / "skills" / "second-skill" / "SKILL.md").read_text(encoding="utf-8"), "# Second Skill\n")

    def test_multi_pack_dry_run_does_not_write_receipts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            registry = temp / "registry"
            target = temp / "install"
            registry.mkdir()
            self.write_pack(registry, skill_only_pack("first", "First Skill", temp / "first-skill"))
            self.write_pack(registry, skill_only_pack("second", "Second Skill", temp / "second-skill"))

            result = self.run_cli("install", "first", "second", "--dry-run", registry=registry, target=target)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Pack: first", result.stdout)
            self.assertIn("Pack: second", result.stdout)
            self.assertFalse((target / "receipts" / "first.json").exists())
            self.assertFalse((target / "receipts" / "second.json").exists())

    def test_uninstalls_multiple_packs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            first_skill = temp / "first-skill"
            second_skill = temp / "second-skill"
            first_skill.mkdir()
            second_skill.mkdir()
            (first_skill / "SKILL.md").write_text("# First Skill\n", encoding="utf-8")
            (second_skill / "SKILL.md").write_text("# Second Skill\n", encoding="utf-8")
            registry = temp / "registry"
            target = temp / "install"
            registry.mkdir()
            self.write_pack(registry, skill_only_pack("first", "First Skill", first_skill))
            self.write_pack(registry, skill_only_pack("second", "Second Skill", second_skill))
            install_result = self.run_cli("install", "first", "second", "--agent", "codex", "--only", "skills", "--mode", "copy", registry=registry, target=target)
            self.assertEqual(install_result.returncode, 0, install_result.stderr)

            result = self.run_cli("uninstall", "first", "second", registry=registry, target=target)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("==> Uninstalling first (1/2)", result.stdout)
            self.assertIn("==> Uninstalling second (2/2)", result.stdout)
            self.assertFalse((target / "receipts" / "first.json").exists())
            self.assertFalse((target / "receipts" / "second.json").exists())
            self.assertFalse((target / ".codex" / "skills" / "first-skill").exists())
            self.assertFalse((target / ".codex" / "skills" / "second-skill").exists())

    def test_upgrades_multiple_packs_using_existing_receipts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            first_skill = temp / "first-skill"
            second_skill = temp / "second-skill"
            first_skill.mkdir()
            second_skill.mkdir()
            (first_skill / "SKILL.md").write_text("# First Skill\n", encoding="utf-8")
            (second_skill / "SKILL.md").write_text("# Second Skill\n", encoding="utf-8")
            registry = temp / "registry"
            target = temp / "install"
            registry.mkdir()
            self.write_pack(registry, skill_only_pack("first", "First Skill", first_skill))
            self.write_pack(registry, skill_only_pack("second", "Second Skill", second_skill))
            install_result = self.run_cli("install", "first", "second", "--agent", "codex", "--only", "skills", "--mode", "copy", registry=registry, target=target)
            self.assertEqual(install_result.returncode, 0, install_result.stderr)

            result = self.run_cli("upgrade", "first", "second", registry=registry, target=target)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("==> Upgrading first (1/2)", result.stdout)
            self.assertIn("==> Upgrading second (2/2)", result.stdout)
            self.assertIn("Upgrading first (mode=copy, conflict=skip, scope=target)", result.stdout)
            self.assertIn("Upgrading second (mode=copy, conflict=skip, scope=target)", result.stdout)
            self.assertTrue((target / "receipts" / "first.json").exists())
            self.assertTrue((target / "receipts" / "second.json").exists())

    def test_plugins_are_pending_unless_execution_is_explicit(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            registry = temp / "registry"
            target = temp / "install"
            registry.mkdir()
            self.write_pack(registry, example_pack(temp / "missing-skill"))

            result = self.run_cli("install", "example", "--only", "plugins", "--mode", "native", registry=registry, target=target)

            self.assertEqual(result.returncode, 0, result.stderr)
            receipt = json.loads((target / "receipts" / "example.json").read_text(encoding="utf-8"))
            capability = receipt["plan"]["capabilities"][0]
            self.assertEqual(capability["type"], "plugin")
            self.assertEqual(capability["status"], "pending")
            self.assertIn("--execute-plugins", capability["reason"])


def example_pack(skill_source):
    return {
        "id": "example",
        "name": "Example Pack",
        "version": "0.1.0",
        "description": "A test pack.",
        "capabilities": [
            {
                "type": "skill",
                "name": "Example Skill",
                "source": str(skill_source),
                "format": "agent-skill",
                "entry": "SKILL.md",
            },
            {
                "type": "plugin",
                "name": "Example plugin",
                "source": "https://example.com/plugin",
                "format": "anthropic-plugin",
                "entry": ".claude-plugin/plugin.json",
                "install": {
                    "method": "manual",
                    "package": "example-plugin",
                    "command": "echo install-plugin",
                },
            },
        ],
    }


def skill_only_pack(pack_id, skill_name, skill_source):
    return {
        "id": pack_id,
        "name": f"{skill_name} Pack",
        "version": "0.1.0",
        "description": "A test pack.",
        "capabilities": [
            {
                "type": "skill",
                "name": skill_name,
                "source": str(skill_source),
                "format": "agent-skill",
                "entry": "SKILL.md",
            }
        ],
    }


if __name__ == "__main__":
    unittest.main()
