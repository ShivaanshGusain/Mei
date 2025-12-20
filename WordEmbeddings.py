import torch
import torch.nn as nn
import torch.optim as optim

class word2vec:
    def __init__(self, sentence = ["The quick brown fox", "jumped over the lazy dog"]):

    
        self.tokens = [s.split() for s in sentence]
        self.vocab = set([word for s in self.tokens for word in s])

        self.word2idex = {w:i for i,w in enumerate(self.vocab)}
        self.idex2word = {i:w for i,w in enumerate(self.vocab)}

        self.vocab_size = len(self.vocab)

        self.data = []

    def skipgram(self, context_window = 1):
        for sentence in self.tokens:
            for i, token in enumerate(sentence):
                for neighbor in sentence[max(i-context_window,0) : min(i+1+context_window, len(sentence))]:
                    if neighbor!=token:
                        self.data.append((token,neighbor))
            
        self.v_embeddings = nn.Embedding(self.vocab_size, self.embedding_dim)
                
        