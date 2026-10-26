#pragma semicolon 1
#pragma newdecls required
#include <sourcemod>
#include <sourcescramble>

#define GAMEDATA "zombie_spawn_fix"
#define PLUGIN_VERSION "1.0.10"

static const char g_sPatchNames[][] =
{
	"ZombieManager::CanZombieSpawnHere::IsInTransitionCondition",
	"CTerrorPlayer::OnPreThinkGhostState::IsInTransitionCondition",
	"CTerrorPlayer::OnPreThinkGhostState::SpawnDisabledCondition",
	"ZombieManager::AccumulateSpawnAreaCollection::EnforceFinaleNavSpawnRulesCondition"
};

// some code from [L4D2] Air Ability Patch (https://forums.alliedmods.net/showthread.php?p=2660278)
public Plugin myinfo =
{
	name = "[L4D2]Zombie Spawn Fix",
	author = "sorallll & Psyk0tik (Crasher_3637)",
	description = "Fixed Special Inected and Player Zombie spawning failures in some cases",
	version = PLUGIN_VERSION,
	url = "https://forums.alliedmods.net/showthread.php?t=333351"
};

public void OnPluginStart()
{
	char sPath[PLATFORM_MAX_PATH];
	BuildPath(Path_SM, sPath, sizeof sPath, "gamedata/%s.txt", GAMEDATA);
	if (!FileExists(sPath))
		SetFailState("\n==========\nMissing required file: \"%s\".\n==========", sPath);

	GameData hGameData = new GameData(GAMEDATA);
	if (!hGameData)
		SetFailState("Failed to load \"%s.txt\" gamedata.", GAMEDATA);

	MemoryPatch patch;
	for (int i; i < sizeof g_sPatchNames; i++) {
		patch = MemoryPatch.CreateFromConf(hGameData, g_sPatchNames[i]);
		if (!patch.Validate()) {
			/*
			 * Common false failure: sourcescramble_manager already applied the same
			 * MemPatch via configs/sourcescramble/zombie_spawn_fix.txt, so verify
			 * bytes no longer match. Prefer this plugin OR the manager config — not both.
			 */
			LogError("Failed to verify patch: \"%s\" (outdated gamedata, or already applied by sourcescramble_manager — remove configs/sourcescramble/zombie_spawn_fix.txt if using this plugin)", g_sPatchNames[i]);
		}
		else if (patch.Enable()) {
			PrintToServer("Enabled patch: \"%s\"", g_sPatchNames[i]);
		}
	}

	delete hGameData;
}
