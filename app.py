#%%
"""Hugging Face/local entry point for the balance-review web app."""

from __future__ import annotations

import os

from web_app.app import create_app


demo = create_app()


#%%
if __name__ == "__main__":
    demo.launch(
        server_name=os.getenv("GRADIO_SERVER_NAME", "0.0.0.0"),
        server_port=int(os.getenv("GRADIO_SERVER_PORT", "7860")),
    )

#%%
