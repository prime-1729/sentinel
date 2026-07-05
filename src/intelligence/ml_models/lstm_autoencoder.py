"""
LSTM Autoencoder for anomaly detection (Layer 2).
Trained on normal flight sequences. High reconstruction error = anomaly.
"""

import os
import numpy as np
import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger("sentinel.ml.lstm")

try:
    import torch
    import torch.nn as nn
    from torch.utils.data import DataLoader, TensorDataset
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False
    logger.warning("PyTorch not available. LSTM Autoencoder training disabled.")

try:
    import onnxruntime as ort
    ORT_AVAILABLE = True
except ImportError:
    ORT_AVAILABLE = False
    logger.warning("ONNX Runtime not available. LSTM inference disabled.")

if TORCH_AVAILABLE:
    class LSTMAutoencoderModel(nn.Module):
        def __init__(self, n_features: int, latent_dim: int = 16):
            super().__init__()
            self.encoder = nn.LSTM(input_size=n_features, hidden_size=64, num_layers=1, batch_first=True)
            self.hidden2latent = nn.Linear(64, latent_dim)
            
            self.latent2hidden = nn.Linear(latent_dim, 64)
            self.decoder = nn.LSTM(input_size=64, hidden_size=64, num_layers=1, batch_first=True)
            self.output_layer = nn.Linear(64, n_features)
            
        def forward(self, x):
            # Encoder
            _, (h_n, _) = self.encoder(x)
            latent = self.hidden2latent(h_n[-1])
            
            # Decoder
            # Repeat latent vector for the sequence length
            seq_len = x.size(1)
            latent_repeated = self.latent2hidden(latent).unsqueeze(1).repeat(1, seq_len, 1)
            
            out, _ = self.decoder(latent_repeated)
            return self.output_layer(out)


class LSTMAutoencoder:
    """
    Sequence-to-sequence autoencoder for temporal anomaly detection.
    """
    def __init__(self, sequence_length: int = 30, n_features: Optional[int] = None, latent_dim: int = 16):
        self.sequence_length = sequence_length
        self.n_features = n_features
        self.latent_dim = latent_dim
        self.model = None
        self.ort_session = None
        self.optimal_threshold = 0.5
        self.is_trained = False

    def build_model(self):
        if not TORCH_AVAILABLE:
            raise RuntimeError("PyTorch is required to build and train the model.")
        self.model = LSTMAutoencoderModel(self.n_features, self.latent_dim)

    def train(self, X_normal: np.ndarray, epochs: int = 20, batch_size: int = 32, learning_rate: float = 1e-3) -> Dict[str, Any]:
        """
        Train on normal sequences.
        X_normal shape: (num_samples, sequence_length, n_features)
        """
        if not TORCH_AVAILABLE:
            raise RuntimeError("PyTorch is required for training.")
            
        if self.n_features is None:
            self.n_features = X_normal.shape[2]
            
        if self.model is None:
            self.build_model()
            
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.model.to(device)
        
        optimizer = torch.optim.Adam(self.model.parameters(), lr=learning_rate)
        criterion = nn.MSELoss()
        
        X_tensor = torch.FloatTensor(X_normal)
        dataset = TensorDataset(X_tensor, X_tensor)
        dataloader = DataLoader(dataset, batch_size=batch_size, shuffle=True)
        
        loss_history = []
        
        for epoch in range(epochs):
            self.model.train()
            epoch_loss = 0
            for batch_x, batch_y in dataloader:
                batch_x = batch_x.to(device)
                batch_y = batch_y.to(device)
                
                optimizer.zero_grad()
                outputs = self.model(batch_x)
                loss = criterion(outputs, batch_y)
                loss.backward()
                optimizer.step()
                
                epoch_loss += loss.item()
                
            avg_loss = epoch_loss / len(dataloader)
            loss_history.append(avg_loss)
            logger.info(f"Epoch {epoch+1}/{epochs} - Loss: {avg_loss:.6f}")
            
        # Compute threshold based on training set reconstruction error
        self.model.eval()
        with torch.no_grad():
            outputs = self.model(X_tensor.to(device))
            mse = torch.mean((outputs - X_tensor.to(device))**2, dim=[1, 2]).cpu().numpy()
            self.optimal_threshold = float(np.mean(mse) + 3 * np.std(mse))
            
        self.is_trained = True
        return {
            "loss_history": loss_history,
            "optimal_threshold": self.optimal_threshold
        }

    def detect(self, X_sequence: np.ndarray) -> List[Dict[str, Any]]:
        """
        Run inference on a batch of sequences.
        X_sequence shape: (batch_size, sequence_length, n_features)
        """
        if not self.is_trained:
            logger.warning("Model not trained or loaded.")
            return []
            
        if self.ort_session is not None and ORT_AVAILABLE:
            # Inference via ONNX
            ort_inputs = {self.ort_session.get_inputs()[0].name: X_sequence.astype(np.float32)}
            ort_outs = self.ort_session.run(None, ort_inputs)
            reconstructed = ort_outs[0]
            mse = np.mean((X_sequence - reconstructed)**2, axis=(1, 2))
        elif self.model is not None and TORCH_AVAILABLE:
            # Inference via PyTorch
            self.model.eval()
            device = next(self.model.parameters()).device
            with torch.no_grad():
                X_tensor = torch.FloatTensor(X_sequence).to(device)
                outputs = self.model(X_tensor)
                mse = torch.mean((outputs - X_tensor)**2, dim=[1, 2]).cpu().numpy()
        else:
            logger.error("No execution backend available.")
            return []
            
        results = []
        for i, error in enumerate(mse):
            is_anomaly = error > self.optimal_threshold
            results.append({
                "reconstruction_error": float(error),
                "is_anomaly": bool(is_anomaly),
                "severity": "CRITICAL" if error > self.optimal_threshold * 2 else "HIGH" if is_anomaly else "NORMAL"
            })
            
        return results

    def export_onnx(self, path: str = "data/models/lstm_ae.onnx") -> str:
        """Export to ONNX for edge deployment."""
        if not TORCH_AVAILABLE or self.model is None:
            raise RuntimeError("Requires PyTorch and a trained model to export.")
            
        os.makedirs(os.path.dirname(path), exist_ok=True)
        
        self.model.eval()
        dummy_input = torch.randn(1, self.sequence_length, self.n_features)
        
        torch.onnx.export(
            self.model,
            dummy_input,
            path,
            export_params=True,
            opset_version=12,
            do_constant_folding=True,
            input_names=['input'],
            output_names=['output'],
            dynamic_axes={'input': {0: 'batch_size'}, 'output': {0: 'batch_size'}}
        )
        
        # Save config alongside
        import json
        config_path = path.replace(".onnx", "_config.json")
        config = {
            "optimal_threshold": float(self.optimal_threshold),
            "n_features": self.n_features,
            "sequence_length": self.sequence_length
        }
        with open(config_path, "w") as f:
            json.dump(config, f)
            
        return path

    @classmethod
    def load_onnx(cls, path: str) -> 'LSTMAutoencoder':
        """Load ONNX model for inference-only."""
        if not ORT_AVAILABLE:
            raise RuntimeError("ONNX Runtime is required for inference.")
            
        config_path = path.replace(".onnx", "_config.json")
        n_features = None
        sequence_length = 30
        optimal_threshold = 0.5
        
        if os.path.exists(config_path):
            import json
            with open(config_path, "r") as f:
                config = json.load(f)
                n_features = config.get("n_features")
                sequence_length = config.get("sequence_length", 30)
                optimal_threshold = config.get("optimal_threshold", 0.5)
        else:
            # Fallback to old threshold file
            threshold_path = path.replace(".onnx", "_threshold.txt")
            if os.path.exists(threshold_path):
                with open(threshold_path, "r") as f:
                    optimal_threshold = float(f.read().strip())
        
        instance = cls(sequence_length=sequence_length, n_features=n_features)
        
        try:
            instance.ort_session = ort.InferenceSession(path)
            instance.is_trained = True
            instance.optimal_threshold = optimal_threshold
        except Exception as e:
            logger.error(f"Failed to load ONNX model: {e}")
            
        return instance
