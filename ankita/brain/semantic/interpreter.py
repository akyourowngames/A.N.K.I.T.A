"""
Semantic Interpreter - Detects user situations from vague statements.

Uses sentence embeddings to match user utterances to predefined situations.
"""

from sentence_transformers import SentenceTransformer, util
import json
import os


class SemanticInterpreter:
    """Interprets user statements to detect semantic situations."""
    
    def __init__(self):
        """Initialize the interpreter with embedding model and situations."""
        print("[SemanticInterpreter] Loading embedding model...")
        self.model = SentenceTransformer('all-MiniLM-L6-v2')
        self.situations = self._load_situations()
        self.phrase_embeddings = self._precompute_embeddings()
        print(f"[SemanticInterpreter] Loaded {len(self.situations)} situations")
    
    def _load_situations(self):
        """Load situation definitions from JSON file."""
        situations_path = os.path.join(os.path.dirname(__file__), 'situations.json')
        with open(situations_path, encoding='utf-8') as f:
            return json.load(f)
    
    def _precompute_embeddings(self):
        """
        Precompute embeddings for all situation phrases.
        This makes detection faster by avoiding re-encoding phrases.
        """
        embeddings = {}
        for situation, data in self.situations.items():
            embeddings[situation] = {
                'phrases': data['phrases'],
                'embeddings': self.model.encode(data['phrases'], convert_to_tensor=True)
            }
        return embeddings
    
    def detect_situation(self, text, threshold=0.6):
        """
        Detect situation from user text using semantic similarity.
        
        Args:
            text: User's input text
            threshold: Minimum similarity score to consider a match (0-1)
        
        Returns:
            {
                'situation': str,
                'confidence': float,
                'matched_phrase': str
            } or None if no match
        """
        user_embedding = self.model.encode(text, convert_to_tensor=True)
        
        best_match = None
        best_score = 0
        best_phrase = None
        
        # Compare against all situation phrases
        for situation, data in self.phrase_embeddings.items():
            similarities = util.cos_sim(user_embedding, data['embeddings'])[0]
            max_sim_idx = similarities.argmax()
            max_sim = similarities[max_sim_idx].item()
            
            if max_sim > best_score:
                best_score = max_sim
                best_match = situation
                best_phrase = data['phrases'][max_sim_idx]
        
        if best_score >= threshold:
            return {
                'situation': best_match,
                'confidence': best_score,
                'matched_phrase': best_phrase
            }
        
        return None
    
    def get_ambiguous_situations(self, text, threshold=0.6, min_diff=0.1):
        """
        Get multiple possible situations if the input is ambiguous.
        
        Args:
            text: User's input text
            threshold: Minimum similarity to consider
            min_diff: Max difference between top matches to consider ambiguous
        
        Returns:
            List of possible situations or None if not ambiguous
        """
        user_embedding = self.model.encode(text, convert_to_tensor=True)
        
        candidates = []
        for situation, data in self.phrase_embeddings.items():
            similarities = util.cos_sim(user_embedding, data['embeddings'])[0]
            max_sim = similarities.max().item()
            
            if max_sim >= threshold:
                candidates.append({
                    'situation': situation,
                    'confidence': max_sim
                })
        
        # Sort by confidence descending
        candidates.sort(key=lambda x: x['confidence'], reverse=True)
        
        # Check if ambiguous (multiple close matches)
        if len(candidates) >= 2:
            if candidates[0]['confidence'] - candidates[1]['confidence'] < min_diff:
                return candidates[:3]  # Return top 3
        
        return None
    
    def get_situation_info(self, situation):
        """Get full information about a situation."""
        return self.situations.get(situation)


# Singleton instance
_interpreter = None


def get_interpreter():
    """Get or create the global interpreter instance."""
    global _interpreter
    if _interpreter is None:
        _interpreter = SemanticInterpreter()
    return _interpreter
