# ERNIE Desktop
Like chatgpt or claude desktop, but for local models
________________________________________________________________

This project built initially for the Baidu ERNIE hackathon, Oct 24-Nov23 2025.
This application is licensed under the MIT license

-Included Linraries
 Bootstrap 5.3.3 (lib/bootstrap*.{css,js}) is released under the MIT License.
 Marked (lib/marked.min.js) is also MIT licensed.
 Highlight.js (lib/highlight*.js/css) is distributed under the BSD 3-Clause
    License.
 pdf.js (lib/pdf*.js) is licensed under Apache License 2.0.


The project aims to provide a full featured AI environment with internet search and document interface similar to CHatGPT or Claude desktop.

It consists of 3 elements:   1. llamacpp (not provided, goes in chat directory), the fastapi server, and the web application.


To use internet search sign up for [tavily](https://auth.tavily.com/u/login/identifier?state=hKFo2SBqUmRZcTktakw5alVYREZXVXhfbkFnZGhsd0gxOHpxdqFur3VuaXZlcnNhbC1sb2dpbqN0aWTZIF9Cb25sa2w4RVFja1p5RmVMVEVYOTItVW5QcEFkSmlXo2NpZNkgUlJJQXZ2WE5GeHBmVFdJb3pYMW1YcUxueVVtWVNUclE)


Llamacpp-server provides inference, simply drop your preferred model into the chat folder along with the proper release from https://github.com/ggml-org/llama.cpp/releases/. 
The fastapi server provides search results to the LLM alongside sytem telemetry ( power, cpu, ram) . You will need to sign up for a free Tavily account, this will get you 1000 searches a month.
The web application uses external libraries to remain fast and small. It provides pdf and text-based document attachments, markdown support for rich chat, streaming chat, and source code highlighting.

To start install requirements.txt located in /search in a python env. Edit example.env and input the model name (or download ERNIE), and put in your tavily key, and the location of your python env. Then rename .env  Then run ./ed.sh, this will start the servers and open the web application in your default browser.
