# Full-schema editing with Spriggit (optional)

[Spriggit](https://github.com/Mutagen-Modding/Spriggit) by Noggog converts a plugin into a folder
of YAML files (one per record, every field named, FormIDs written as `012EB7:Skyrim.esm`) and back.
It is built on [Mutagen](https://github.com/Mutagen-Modding/Mutagen), which knows every Skyrim
record type. Use it for what `esp.py` keeps as raw hex: RACE data, QUST aliases/objectives, PACK
procedures, SCEN actions, PERK entry points, WTHR/IMAD colors, BPTD, and for authoring complex
records from scratch.

Cost: the .NET 10 SDK (~200 MB) and internet access on first use (it downloads its
`Spriggit.Yaml.Skyrim` package from NuGet).

## Install

1. .NET SDK 10: https://dotnet.microsoft.com/download (Windows: `winget install Microsoft.DotNet.SDK.10`;
   Linux/macOS: the `dotnet-install.sh` script works without root:
   `curl -sSL https://dot.net/v1/dotnet-install.sh | bash -s -- --channel 10.0`).
2. `dotnet tool install --global Spriggit.CLI` (then `spriggit --help`; make sure
   `~/.dotnet/tools` / `%USERPROFILE%\.dotnet\tools` is on PATH).

## Use

```bash
# plugin -> YAML (-v is required together with -p/-g)
spriggit serialize -i "MyMod.esp" -o MyMod_yaml -g SkyrimSE -p Spriggit.Yaml -v 0.41.0

# edit the YAML (e.g. MyMod_yaml/Weapons/IronSword - 012EB7_Skyrim.esm.yaml)

# YAML -> plugin (package/version are read from spriggit-meta.json)
spriggit deserialize -i MyMod_yaml -o "MyMod.esp"
```

Then check the result with this skill: `esp diff Original.esp MyMod.esp`, `esp verify MyMod.esp`.

Notes
- Spriggit sorts some lists (e.g. script properties) and may normalize a few fields, so a
  serialize/deserialize round trip is equivalent but not always byte-identical.
- Records are matched by FormKey, so copying a YAML file into another mod's folder copies the record;
  masters are recomputed on deserialize.
- Use a newer `-v` when Spriggit releases one (`dotnet tool update -g Spriggit.CLI`).
- `spriggit serialize` refuses unknown data by default (safe). Don't bypass it on files you
  need to keep intact.

## Mutagen / Synthesis for big automated patches

For load-order-wide automated patches (e.g. "apply X to every NPC in my 1500-plugin load order"),
the usual tool is [Synthesis](https://github.com/Mutagen-Modding/Synthesis) (C# patchers on
Mutagen). For one-off or targeted work, `esp.py` and its Python API are simpler.
