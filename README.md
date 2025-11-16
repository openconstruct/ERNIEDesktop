# ERNIE Desktop
Local AI desktop for ERNIE / GGUF models on Linux & SBCs (Radxa, Pi, etc.)
________________________________________________________________

<img width="1280" height="720" alt="Screenshot from 2025-11-13 07-34-11" src="https://github.com/user-attachments/assets/b457cb46-5b39-4423-937e-503199a9db29" />

This project built initially for the Baidu ERNIE hackathon, Oct 24-Nov23 2025.
This application is licensed under the MIT license

Designed as a free and open source alternative to apps like ChatGPT and Claude Desktop.

-Included Libraries

- Bootstrap 5.3.3 (lib/bootstrap*.{css,js}) is released under the MIT License.
- Marked (lib/marked.min.js) is also MIT licensed.
- Highlight.js (lib/highlight*.js/css) is distributed under the BSD 3-Clause
    License.
- pdf.js (lib/pdf*.js) is licensed under Apache License 2.0.

 *ERNIE Desktop* 
 
 ERNIE Desktop is a lightweight application to provide a nice GUI and toolset for running LLM models on SBCs or computers. It functions on ARM and AMD64 Linux currently, with plans to package it for windows.  ERNIE Desktop is designd for low cost, low power SBC systems, but also can run on a regular Linux PC.



*Getting started*

To use internet search sign up for [tavily](https://auth.tavily.com/u/login/identifier?state=hKFo2SBqUmRZcTktakw5alVYREZXVXhfbkFnZGhsd0gxOHpxdqFur3VuaXZlcnNhbC1sb2dpbqN0aWTZIF9Cb25sa2w4RVFja1p5RmVMVEVYOTItVW5QcEFkSmlXo2NpZNkgUlJJQXZ2WE5GeHBmVFdJb3pYMW1YcUxueVVtWVNUclE)

You will need to download or build llamacpp for your architecture. You can find prebuilt binaries for many systems [here](https://github.com/ggml-org/llama.cpp/releases/) . If you need to build from source visit llamacpp [here](https://github.com/ggml-org/llama.cpp) and follow instructions.  Put the contents of the zip ( or your build/bin directory if you built from source) into the chat directory.

Then you need to get a model in gguf format from someplace liek huggingface. Also lace it into the chat directory, or wherever you would like, you will need to imput model path in the .env file later.

Next create a python env and install requirements.txt in ERNIEDesktop/search

Then edit example.env and add your settings such as model name and path, llama-server commandline, ports, and tavily key.

Finally run ed.sh, mark it as executable if you get a permissions error. This should launch both servers and open the web application.

*About*

ERNIE  Desktop is comprised of 3 main parts. 
- llamcpp Provides inference via API
- fastAPI server Provides internet search, and device analytics
- web application Provides the UI, control center, and document interface

  This software has been tested thouroughly on an AMD laptop and a Radxa Orion o6 ARM development board.

  
