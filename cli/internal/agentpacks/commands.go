package agentpacks

import (
	"encoding/json"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"time"

	"github.com/sandeshh/agent-packs/cli/internal/config"
	"github.com/sandeshh/agent-packs/cli/internal/install"
	"github.com/sandeshh/agent-packs/cli/internal/model"
	"github.com/sandeshh/agent-packs/cli/internal/registry"
	"github.com/sandeshh/agent-packs/cli/internal/util"
	"gopkg.in/yaml.v3"
)

func Doctor(defaultRegistry, home string, out io.Writer) error {
	checks := []struct{ name, command string }{
		{"git", "git"}, {"go", "go"},
		{"claude", "claude"}, {"codex", "codex"}, {"cursor", "cursor"},
		{"gemini", "gemini"}, {"goose", "goose"}, {"opencode", "opencode"},
		{"gh", "gh"},
	}
	for _, check := range checks {
		if _, err := exec.LookPath(check.command); err != nil {
			fmt.Fprintf(out, "WARN  %s not found\n", check.name)
		} else {
			fmt.Fprintf(out, "OK    %s found\n", check.name)
		}
	}

	if _, err := os.Stat(defaultRegistry); err != nil {
		fmt.Fprintf(out, "WARN  registry unavailable: %s\n", defaultRegistry)
	} else {
		fmt.Fprintf(out, "OK    registry available: %s\n", defaultRegistry)
	}

	if err := os.MkdirAll(util.ExpandHome(home), 0o755); err != nil {
		fmt.Fprintf(out, "WARN  install home not writable: %s\n", home)
	} else {
		fmt.Fprintf(out, "OK    install home writable: %s\n", home)
	}

	summaries, err := install.ListInstalledReceipts(home)
	if err == nil {
		fmt.Fprintf(out, "INFO  %d pack(s) installed in %s\n", len(summaries), home)
	}

	checkIndexFreshness(defaultRegistry, out)
	return nil
}

func checkIndexFreshness(registryDir string, out io.Writer) {
	indexPath := filepath.Join(filepath.Dir(registryDir), "index.json")
	indexData, err := os.ReadFile(indexPath)
	if err != nil {
		fmt.Fprintf(out, "WARN  registry index not found: %s\n", indexPath)
		return
	}
	var idx model.RegistryIndex
	if err := json.Unmarshal(indexData, &idx); err != nil || idx.GeneratedAt == "" {
		fmt.Fprintf(out, "WARN  registry index unreadable\n")
		return
	}
	indexTime, err := time.Parse(time.RFC3339, idx.GeneratedAt)
	if err != nil {
		fmt.Fprintf(out, "WARN  registry index has invalid generatedAt\n")
		return
	}
	entries, _ := os.ReadDir(registryDir)
	var latestPack time.Time
	for _, entry := range entries {
		if entry.IsDir() || filepath.Ext(entry.Name()) != ".json" {
			continue
		}
		info, err := entry.Info()
		if err == nil && info.ModTime().After(latestPack) {
			latestPack = info.ModTime()
		}
	}
	if !latestPack.IsZero() && latestPack.After(indexTime) {
		fmt.Fprintf(out, "WARN  registry index is stale (run agent-packs index --output registry/index.json)\n")
	} else {
		fmt.Fprintf(out, "OK    registry index is fresh\n")
	}
}

func Sync(registryPath, home, projectDir, target, agent, mode string, out io.Writer) error {
	cfg, err := config.LoadProjectConfig(projectDir)
	if err != nil {
		return fmt.Errorf("no .agent-packs.yaml in %s (run agent-packs init first): %w", projectDir, err)
	}
	if len(cfg.Packs) == 0 {
		fmt.Fprintln(out, "No packs configured in .agent-packs.yaml (add a 'packs' list)")
		return nil
	}

	summaries, _ := install.ListInstalledReceipts(target)
	installedIDs := make(map[string]bool, len(summaries))
	for _, s := range summaries {
		installedIDs[s.ID] = true
	}

	options := model.InstallOptions{Mode: mode, OnConflict: "skip"}
	for _, packID := range cfg.Packs {
		if installedIDs[packID] {
			fmt.Fprintf(out, "already installed: %s\n", packID)
			continue
		}
		fmt.Fprintf(out, "installing: %s\n", packID)
		if err := install.InstallWithOptions(registryPath, home, packID, target, agent, "all", false, false, options, out); err != nil {
			return fmt.Errorf("failed to install %s: %w", packID, err)
		}
	}
	return nil
}

func Freeze(target, projectDir string, out io.Writer) error {
	summaries, err := install.ListInstalledReceipts(target)
	if err != nil {
		return err
	}
	cfg, _ := config.LoadProjectConfig(projectDir)
	cfg.Packs = make([]string, 0, len(summaries))
	for _, s := range summaries {
		cfg.Packs = append(cfg.Packs, s.ID)
	}
	sort.Strings(cfg.Packs)
	if err := config.SaveProjectConfig(projectDir, cfg); err != nil {
		return err
	}
	fmt.Fprintf(out, "Wrote %d pack(s) to %s/.agent-packs.yaml\n", len(cfg.Packs), projectDir)
	return nil
}

func ExportPacks(target string, out io.Writer) error {
	summaries, err := install.ListInstalledReceipts(target)
	if err != nil {
		return err
	}
	packs := make([]string, 0, len(summaries))
	for _, s := range summaries {
		packs = append(packs, s.ID)
	}
	sort.Strings(packs)
	type exportFile struct {
		Packs []string `yaml:"packs"`
	}
	enc := yaml.NewEncoder(out)
	return enc.Encode(exportFile{Packs: packs})
}

func ScanSkills(root string, out io.Writer) error {
	root = util.ExpandHome(root)
	return filepath.WalkDir(root, func(path string, d os.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if !d.IsDir() && filepath.Base(path) == "SKILL.md" {
			manifest, err := registry.LoadSkillManifest(path)
			if err != nil {
				fmt.Fprintf(out, "WARN  %s: %s\n", path, err)
				return nil
			}
			fmt.Fprintf(out, "%s\t%s\n", manifest.Name, path)
		}
		return nil
	})
}

func ImportSkills(sourceDir, target string, out io.Writer) error {
	importDir := filepath.Join(util.ExpandHome(target), "sources", "imported")
	if err := os.MkdirAll(importDir, 0o755); err != nil {
		return err
	}
	return filepath.WalkDir(util.ExpandHome(sourceDir), func(path string, d os.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if d.IsDir() || filepath.Base(path) != "SKILL.md" {
			return nil
		}
		manifest, err := registry.LoadSkillManifest(path)
		if err != nil {
			return nil
		}
		dest := filepath.Join(importDir, util.Slugify(manifest.Name))
		if err := os.RemoveAll(dest); err != nil {
			return err
		}
		if err := util.CopyDir(filepath.Dir(path), dest); err != nil {
			return err
		}
		fmt.Fprintf(out, "imported\t%s\t%s\n", manifest.Name, dest)
		return nil
	})
}
