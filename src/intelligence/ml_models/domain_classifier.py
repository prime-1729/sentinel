"""
Domain Classifier for anomaly identification (Layer 3).
Only runs AFTER Layer 1 or 2 flags an anomaly.
Classifies the anomaly into a specific fault domain (propulsion, power, navigation, etc.).
"""

import os
import joblib
import numpy as np
from typing import Dict, Any, List, Optional
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split

class DomainClassifier:
    """
    Supervised classifier: given features at anomaly timestamp, classify fault domain.
    """
    DEFAULT_MODEL_PATH = "data/models/domain_classifier.joblib"
    
    # Supported fault domains
    DOMAINS = [
        "propulsion", 
        "power", 
        "navigation", 
        "dynamics", 
        "ew", 
        "thermal",
        "communication",
        "environmental",
        "structural",
        "payload",
        "unknown"
    ]
    
    def __init__(self, n_estimators: int = 100, random_state: int = 42):
        self.n_estimators = n_estimators
        self.random_state = random_state
        self.model: Optional[RandomForestClassifier] = None
        self.scaler: Optional[StandardScaler] = None
        self.feature_names: Optional[List[str]] = None
        self.is_trained = False
        
    def train(self, X: np.ndarray, y: np.ndarray, feature_names: List[str]) -> Dict[str, Any]:
        """
        Train the domain classifier.
        
        Args:
            X: Feature matrix
            y: Array of string labels (must match items in DOMAINS)
            feature_names: List of feature names
            
        Returns:
            Dictionary with training statistics
        """
        self.feature_names = feature_names
        
        # Ensure y only contains known domains, map others to "unknown"
        y_clean = np.array([label if label in self.DOMAINS else "unknown" for label in y])
        
        self.scaler = StandardScaler()
        X_scaled = self.scaler.fit_transform(X)
        
        # Train/test split for meaningful accuracy reporting
        X_train, X_test, y_train, y_test = train_test_split(X_scaled, y_clean, test_size=0.2, random_state=self.random_state)
        
        self.model = RandomForestClassifier(
            n_estimators=self.n_estimators,
            random_state=self.random_state,
            n_jobs=-1,
            class_weight="balanced"
        )
        
        self.model.fit(X_train, y_train)
        self.is_trained = True
        
        # Calculate accuracy on train and test sets
        train_acc = self.model.score(X_train, y_train)
        test_acc = self.model.score(X_test, y_test) if len(X_test) > 0 else 0.0
        
        return {
            "samples": len(X),
            "features": len(feature_names),
            "classes": list(self.model.classes_),
            "train_accuracy": float(train_acc),
            "test_accuracy": float(test_acc)
        }
        
    def classify(self, features: np.ndarray) -> Dict[str, Any]:
        """
        Classify a single anomaly event.
        
        Args:
            features: 1D array of features for the anomalous timestamp
            
        Returns:
            Dict containing domain, confidence, and top contributing features
        """
        if not self.is_trained or self.model is None or self.scaler is None:
            return {
                "domain": "unknown",
                "confidence": 0.0,
                "top_features": []
            }
            
        # Ensure 2D shape for scaler (1, n_features)
        if len(features.shape) == 1:
            X = features.reshape(1, -1)
        else:
            X = features
            
        X_scaled = self.scaler.transform(X)
        
        # Get prediction and probabilities
        pred_class = self.model.predict(X_scaled)[0]
        probs = self.model.predict_proba(X_scaled)[0]
        
        class_idx = np.where(self.model.classes_ == pred_class)[0][0]
        confidence = float(probs[class_idx])
        
        # Extract feature importances to determine why this classification was made
        # We multiply global feature importances by the scaled values of this specific instance
        instance_importances = np.abs(self.model.feature_importances_ * X_scaled[0])
        top_indices = np.argsort(instance_importances)[-3:][::-1]
        
        top_features = []
        if self.feature_names:
            for idx in top_indices:
                top_features.append({
                    "name": self.feature_names[idx],
                    "value": float(X[0, idx]),
                    "importance": float(instance_importances[idx])
                })
                
        return {
            "domain": pred_class,
            "confidence": confidence,
            "top_features": top_features
        }
        
    def save(self, path: str = None) -> str:
        """Save the trained model."""
        if not self.is_trained:
            raise RuntimeError("Model not trained yet.")

        path = path or self.DEFAULT_MODEL_PATH
        model_dir = os.path.dirname(path)
        if model_dir and not os.path.exists(model_dir):
            os.makedirs(model_dir, exist_ok=True)

        payload = {
            'model': self.model,
            'scaler': self.scaler,
            'feature_names': self.feature_names,
            'n_estimators': self.n_estimators
        }
        joblib.dump(payload, path)
        return path

    @classmethod
    def load(cls, path: str = None) -> 'DomainClassifier':
        """Load a trained model."""
        path = path or cls.DEFAULT_MODEL_PATH
        if not os.path.exists(path):
            raise FileNotFoundError(f"No trained model found at {path}")

        payload = joblib.load(path)
        classifier = cls(n_estimators=payload.get('n_estimators', 100))
        classifier.model = payload['model']
        classifier.scaler = payload['scaler']
        classifier.feature_names = payload.get('feature_names')
        classifier.is_trained = True
        return classifier
