This repository works with the OmniParser fork that I have created, which solves the issue with the current official Repository - 
Official repo - https://github.com/microsoft/OmniParser


This AI Agent is currently in progress, to use and check the components of this model - 
1. Download the weights from Hugging Face - https://huggingface.co/microsoft/OmniParser-v2.0/tree/main 
2. Download My OmniParser repository and paste that in the following location - ROOT\Mei\perception\Visual
3. Inside the OmniParser folder, create another folder "weights" and paste the HuggingFace files in this folder, it should look like - 
   - "ROOT\Mei\perception\Visual\OmniParser\weights\icon_caption" and "ROOT\Mei\perception\Visual\OmniParser\weights\icon_detect"
4. Create another temp folder in the main directory - "Mei\temp" and place your screenshot with the name - "screen.png"

It also uses - 
Faster whisper  specifically the model =  mukowaty/faster-whisper-int8 
qwen2.5-3b-instruct-q4_k_m From - https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF/tree/main

  #NOTE - Place these both in - ROOT\models and not in - ROOT\Mei\models
Dolphin3.0-Llama3.1-8B-exl2 from = https://huggingface.co/Andycurrent/Dolphin3.0-Llama3.1-8B/tree/main

  #NOTE - Place this in - ROOT\Dolphin3.0-Llama3.1-8B-exl2


With this, you can run the element_detector.py module as is. 
This also acts as proof that my fix for OmniParser is running and works correctly with Python version 3.11
and faces no issue with PaddleOCR v2.9+

With this, the entire build is complete. There are still issues with the cursor click location; those are being addressed.

#NOTE - 
You can try using the official OmniParser repository.
However, you will face issues with invalid parameters and other errors related to OmniParser's link to PaddleOCR.
