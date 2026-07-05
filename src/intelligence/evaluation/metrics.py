import numpy as np
import pandas as pd
from typing import Dict, List, Tuple
from sklearn.metrics import precision_score, recall_score, f1_score, roc_auc_score, average_precision_score, confusion_matrix

def compute_detection_metrics(y_true: np.ndarray, y_pred: np.ndarray, y_scores: np.ndarray) -> Dict[str, float]:
    """
    Compute standard ML evaluation metrics.
    
    Args:
        y_true: Ground truth labels (0=normal, 1=anomaly)
        y_pred: Predicted labels (0=normal, 1=anomaly)
        y_scores: Raw anomaly scores (higher = more anomalous)
        
    Returns:
        Dictionary of metrics
    """
    metrics = {}
    
    # Check if there are any anomalies in the ground truth
    has_anomalies = np.sum(y_true) > 0
    has_normal = np.sum(y_true == 0) > 0
    
    # Basic metrics
    metrics['precision'] = float(precision_score(y_true, y_pred, zero_division=0))
    metrics['recall'] = float(recall_score(y_true, y_pred, zero_division=0))
    metrics['f1'] = float(f1_score(y_true, y_pred, zero_division=0))
    
    # AUC metrics (only valid if both classes are present)
    if has_anomalies and has_normal:
        metrics['roc_auc'] = float(roc_auc_score(y_true, y_scores))
        metrics['pr_auc'] = float(average_precision_score(y_true, y_scores))
    else:
        metrics['roc_auc'] = 0.0
        metrics['pr_auc'] = 0.0
        
    # Confusion matrix elements
    tn, fp, fn, tp = confusion_matrix(y_true, y_pred, labels=[0, 1]).ravel()
    metrics['tn'] = int(tn)
    metrics['fp'] = int(fp)
    metrics['fn'] = int(fn)
    metrics['tp'] = int(tp)
    
    return metrics

def compute_detection_latency(fault_timestamps: List[float], alert_timestamps: List[float]) -> Dict[str, float]:
    """
    Compute how quickly the system detects faults.
    
    Args:
        fault_timestamps: Times when faults were injected
        alert_timestamps: Times when the system fired an alert
        
    Returns:
        Dictionary with latency metrics
    """
    latencies = []
    missed_faults = 0
    
    for fault_t in fault_timestamps:
        # Find the first alert that happened after the fault
        valid_alerts = [t for t in alert_timestamps if t >= fault_t]
        
        if valid_alerts:
            first_alert = min(valid_alerts)
            latency = first_alert - fault_t
            
            # If the alert took more than 60 seconds, it's probably not related to this fault
            if latency <= 60.0:
                latencies.append(latency)
            else:
                missed_faults += 1
        else:
            missed_faults += 1
            
    if not latencies:
        return {
            'mean_latency_s': 0.0,
            'median_latency_s': 0.0,
            'p95_latency_s': 0.0,
            'missed_faults': missed_faults
        }
        
    return {
        'mean_latency_s': float(np.mean(latencies)),
        'median_latency_s': float(np.median(latencies)),
        'p95_latency_s': float(np.percentile(latencies, 95)),
        'missed_faults': missed_faults
    }

def calculate_false_alarm_rate(y_true: np.ndarray, y_pred: np.ndarray, timestamps: np.ndarray) -> float:
    """
    Calculate false alarms per hour.
    
    Args:
        y_true: Ground truth
        y_pred: Predictions
        timestamps: Timestamps for each reading in seconds
        
    Returns:
        False alarms per hour
    """
    if len(timestamps) < 2:
        return 0.0
        
    total_hours = (timestamps[-1] - timestamps[0]) / 3600.0
    if total_hours <= 0:
        return 0.0
        
    # Count continuous blocks of false positives as single alarms
    # to avoid counting 100 consecutive FP readings as 100 alarms
    false_positives = (y_true == 0) & (y_pred == 1)
    
    # Find transitions from False to True
    fp_starts = np.diff(false_positives.astype(int), prepend=0) == 1
    num_alarms = np.sum(fp_starts)
    
    return float(num_alarms / total_hours)
