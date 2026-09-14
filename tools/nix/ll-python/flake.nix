{
  # Python interpreter for the local LibreLane venv (.tools/venv-ll): the same
  # Python the LibreLane flake builds Yosys/OpenROAD against, plus tkinter,
  # which LibreLane needs to evaluate PDK Tcl configuration files, and the
  # Nix-built KLayout Python module (pya) matching the flake's klayout binary.
  description = "Tk-enabled Python from the pinned LibreLane flake";
  inputs.librelane.url = "github:librelane/librelane/3.1.0.dev3";
  outputs = { self, librelane }: {
    packages.x86_64-linux.default =
      librelane.legacyPackages.x86_64-linux.python3.withPackages (ps: [ ps.tkinter ps.klayout ]);
  };
}
