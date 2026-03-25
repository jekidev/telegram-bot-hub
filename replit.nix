{ pkgs }: {
  deps = [
    pkgs.python311
    pkgs.python311Packages.pip
    pkgs.python311Packages.flask
    pkgs.git
    pkgs.postgresql  # for local db testing
  ];
  env = {
    PYTHON_VERSION = "3.11";
    PYTHONPATH = "${pkgs.python311}/lib/python3.11";
  };
}
