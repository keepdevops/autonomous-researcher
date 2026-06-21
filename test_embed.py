from llama_cpp import Llama

embd = Llama(
    model_path="./nomic-embed-text-v1.5.Q8_0.gguf", 
    embedding=True, 
    n_ctx=8192
)

text = "search_query: What is the optimal pipeline structure for autonomous AI agents?"
output = embd.embed(text)

print("Embedding vector length:", len(output))
print("Vector preview:", output[:5])
