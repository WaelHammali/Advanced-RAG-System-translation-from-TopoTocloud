"""Compatibility launcher; application code lives in net2cloud."""

from net2cloud.app import main, plan_architecture

__all__ = ["main", "plan_architecture"]

if __name__ == "__main__":
    raise SystemExit(main())
