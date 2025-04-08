{
  inputs.nixpkgs.url = github:NixOS/nixpkgs/nixos-21.11;
  inputs.python-zulip-api-src = {
    url = github:Kha/python-zulip-api/lean;
    flake = false;
  };

  outputs = { self, nixpkgs, python-zulip-api-src }:
  let system = "x86_64-linux";
  in with nixpkgs.legacyPackages.${system}; rec {

    packages.${system} = rec {
      python-zulip-api =
        with python3Packages;
        buildPythonPackage {
          name = "python-zulip-api";
          propagatedBuildInputs = [ requests matrix-client distro click typing-extensions ];
          src = "${python-zulip-api-src}/zulip";
          doCheck = false;
        };

      rss-bot =
        with python3Packages;
        buildPythonApplication {
          name = "rss-bot";
          propagatedBuildInputs = [ python-zulip-api feedparser ];
          src = "${python-zulip-api-src}/zulip/integrations/rss";
          prePatch = ''
            cat <<EOF > setup.py
#!/usr/bin/env python

from setuptools import setup, find_packages

setup(name='rss-bot',
      version='1.0',
      packages=find_packages(),
      scripts=["rss-bot"],
     )
EOF
          '';
        };

      lean4-nightly-bot =
        with python3Packages;
        buildPythonApplication {
          name = "lean4-nightly.py";
          propagatedBuildInputs = [ tweepy PyGithub ];
          src = ./lean4-nightly-bot;
        };

      velcom-bot =
        with python3Packages;
        buildPythonApplication {
          name = "velcom-bot.py";
          propagatedBuildInputs = [ python-zulip-api ];
          src = ./velcom-bot;
        };
    };

    nixosModule.config = {
      systemd.services.lean4-nightly-bot = {
        startAt = "09:30 UTC";  # CI runs at 07:00 UTC
        # override in machine config
        #environment = { "CONSUMER_KEY" = ""; "CONSUMER_SECRET" = ""; "ACCESS_TOKEN" = ""; "ACCESS_TOKEN_SECRET" = ""; }
        # should probably use serviceConfig.SetCredentialEncrypted starting with systemd v250
        serviceConfig = {
          DynamicUser = true;
          ExecStart = "${packages.${system}.lean4-nightly-bot}/bin/lean4-nightly.py";
        };
      };

      systemd.services.lean-rss-bot = {
        startAt = "*:00/5";  # every 5 minutes
        # override in machine config
        #environment = { "ZULIP_EMAIL" = "bot-bot@leanprover.zulipchat.com"; "ZULIP_API_KEY" = ""; "ZULIP_SITE" = "https://leanprover.zulipchat.com"; };
        serviceConfig = {
          DynamicUser = true;
          StateDirectory = "rss-bot";
          Type = "exec";
          ExecStart = "${packages.${system}.rss-bot}/bin/rss-bot --feed-file=${./rss-feeds} --data-dir=\${STATE_DIRECTORY} --pr-links";
          TimeoutSec = "5min";
        };
      };

      systemd.services.lean-velcom-bot = {
        startAt = "*:00/5";  # every 5 minutes
        # override in machine config
        #environment = { "ZULIP_EMAIL" = "bot-bot@leanprover.zulipchat.com"; "ZULIP_API_KEY" = ""; "ZULIP_SITE" = "https://leanprover.zulipchat.com"; };
        serviceConfig = {
          DynamicUser = true;
          StateDirectory = "velcom-bot";
          Type = "exec";
          ExecStart = "${packages.${system}.velcom-bot}/bin/velcom-bot.py --feed-file=${./velcom-urls} --data-dir=\${STATE_DIRECTORY}";
          TimeoutSec = "5min";
        };
      };
    };

  };
}
