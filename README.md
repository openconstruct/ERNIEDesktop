# ERNIEDesktop
Like chatgpt or claude desktop, but for local models
________________________________________________________________

This project built initially for the Baidu ERNIE hackathon, Oct 24-Nov23 2025.

The project aims to provide a full featured AL environment with internet search and document interface.

It consists of 3 elements:   1. llamacpp (not provided, goes in chat directory), the fastapi taviley search server, and the web application.

Llamacpp-server provides inference, simply drop your preferred model into the chat folder along with the proper release from https://github.com/ggml-org/llama.cpp/releases/.
The fastapi server provides search results to the LLM. You will need to sign up for a free Tavily account, this will get you 1000 searches a month.
The web application uses external libraries to remain fast and small. It provides pdf and text-based document attachments, markdown support for rich chat, streaming chat, and source code highlighting.

To start edit settings.ini and input the model name (or download ERNIE), and put in your tavily key. The run ED.sh, this will start the servers and open the web application in your default browser.
