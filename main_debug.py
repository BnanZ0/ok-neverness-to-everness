if __name__ == "__main__":
    from src.config import config
    from src.patches.startup_patches import install_startup_patches

    install_startup_patches()

    import ok

    config["debug"] = True
    ok_instance = ok.OK(config)
    ok_instance.start()
