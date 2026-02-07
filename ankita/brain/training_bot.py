"""
Training Bot - Automated 24/7 trainer for Ankita
"""
import time
import json
from datetime import datetime
from brain.scenario_generator import ScenarioGenerator
from brain.context_collector import get_current_context
from brain.learning_db import get_db
from brain.hybrid_intelligence import get_hybrid_ai


class TrainingBot:
    """
    Automated bot that trains Ankita 24/7.
    Generates realistic interactions and provides feedback.
    """
    
    def __init__(self, interactions_per_hour=60, log_file="training_log.json"):
        self.speed = interactions_per_hour
        self.log_file = log_file
        
        self.generator = ScenarioGenerator()
        self.db = get_db()
        self.hybrid_ai = get_hybrid_ai()
        
        self.stats = {
            'total_interactions': 0,
            'successes': 0,
            'failures': 0,
            'start_time': datetime.now().isoformat()
        }
    
    def evaluate_response(self, scenario, action_taken, action_result):
        """
        Evaluate if Ankita's response was good.
        
        Returns:
            float: Reward 0-1
        """
        reward = 0.0
        
        # Did the action succeed?
        if action_result.get('status') == 'success':
            reward += 0.5
        
        # Was it the expected action?
        if action_taken == scenario['expected_action']:
            reward += 0.3
        
        # Time-appropriate?
        situation = scenario['situation']
        hour = scenario['hour']
        
        if situation == "hungry":
            if hour < 10 and 'breakfast' in str(action_result).lower():
                reward += 0.2
            elif 12 <= hour < 15 and 'lunch' in str(action_result).lower():
                reward += 0.2
            elif hour >= 18 and 'dinner' in str(action_result).lower():
                reward += 0.2
        
        # Battery-aware?
        if scenario['context']['battery_percent'] < 20:
            if 'youtube' not in action_taken and 'chrome' not in action_taken:
                reward += 0.1  # Smart not to drain battery
        
        return min(reward, 1.0)
    
    def run_single_interaction(self, scenario=None):
        """
        Run one training interaction.
        
        Returns:
            dict: Result with reward
        """
        # Generate scenario
        if scenario is None:
            scenario = self.generator.generate_scenario()
        
        if not scenario:
            return None
        
        query = scenario['query']
        context = scenario['context']
        situation = scenario['situation']
        
        print(f"\n[TrainingBot] Query: '{query}' (situation: {situation}, hour: {context['hour']})")
        
        # Simulate Ankita processing
        # For now, we just log to database and let learning systems learn
        # In full implementation, would actually call Ankita
        
        # For demo: assume action was taken
        action_taken = scenario['expected_action']
        action_result = {'status': 'success'}
        
        # Evaluate
        reward = self.evaluate_response(scenario, action_taken, action_result)
        
        print(f"[TrainingBot] Action: {action_taken}, Reward: {reward:.2f}")
        
        # Log to database for learning
        success = 1 if reward > 0.5 else 0
        
        self.db.log_action(
            context=context,
            action=action_taken,
            params={'query': query},
            success=success,
            exec_time_ms=0
        )
        
        # Update hybrid AI learning systems
        self.hybrid_ai.learn_from_outcome(
            user_text=query,
            situation=situation,
            context=context,
            action=action_taken,
            params={'query': query},
            success=success
        )
        
        # Update stats
        self.stats['total_interactions'] += 1
        if success:
            self.stats['successes'] += 1
        else:
            self.stats['failures'] += 1
        
        return {
            'scenario': scenario,
            'action': action_taken,
            'reward': reward,
            'success': success
        }
    
    def run_batch(self, count=100, save_interval=10):
        """
        Run batch of training interactions.
        
        Args:
            count: Number of interactions
            save_interval: Save stats every N interactions
        """
        print(f"\n[TrainingBot] Starting batch training: {count} interactions")
        print(f"[TrainingBot] Speed: {self.speed} interactions/hour\n")
        
        for i in range(count):
            result = self.run_single_interaction()
            
            if result:
                # Save stats periodically
                if (i + 1) % save_interval == 0:
                    self.save_stats()
                    self.print_progress()
            
            # Wait before next interaction (simulate real time)
            # For testing, use very short delays
            # time.sleep(3600 / self.speed)  # Commented for fast testing
        
        print(f"\n[TrainingBot] Batch complete!")
        self.print_progress()
        self.save_stats()
    
    def run_continuous(self, duration_hours=None):
        """
        Run continuous training.
        
        Args:
            duration_hours: Hours to run, or None for infinite
        """
        print(f"\n[TrainingBot] Starting continuous training")
        if duration_hours:
            print(f"[TrainingBot] Duration: {duration_hours} hours")
        else:
            print(f"[TrainingBot] Duration: Infinite (Ctrl+C to stop)")
        
        start_time = time.time()
        
        try:
            interaction_count = 0
            while True:
                # Check if duration exceeded
                if duration_hours:
                    elapsed_hours = (time.time() - start_time) / 3600
                    if elapsed_hours >= duration_hours:
                        break
                
                # Run interaction
                self.run_single_interaction()
                interaction_count += 1
                
                # Save stats every 50 interactions
                if interaction_count % 50 == 0:
                    self.save_stats()
                    self.print_progress()
                
                # Wait
                time.sleep(3600 / self.speed)
        
        except KeyboardInterrupt:
            print("\n[TrainingBot] Stopped by user")
        
        print(f"\n[TrainingBot] Training complete!")
        self.print_progress()
        self.save_stats()
    
    def print_progress(self):
        """Print current training progress."""
        total = self.stats['total_interactions']
        successes = self.stats['successes']
        
        print(f"\n=== Training Progress ===")
        print(f"Total interactions: {total}")
        print(f"Successes: {successes} ({successes/total*100 if total > 0 else 0:.1f}%)")
        print(f"Failures: {self.stats['failures']}")
        
        # Get DB stats
        db_stats = self.db.get_recent_actions(limit=1)
        total_logged = len(list(self.db.conn.execute("SELECT COUNT(*) FROM action_history").fetchone()))
        print(f"Total in database: {total_logged}")
    
    def save_stats(self):
        """Save training stats to file."""
        with open(self.log_file, 'w') as f:
            json.dump(self.stats, f, indent=2)


def main():
    """Main entry point for training bot."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Ankita Training Bot')
    parser.add_argument('--mode', choices=['batch', 'continuous'], default='batch',
                        help='Training mode')
    parser.add_argument('--count', type=int, default=100,
                        help='Number of interactions for batch mode')
    parser.add_argument('--speed', type=int, default=60,
                        help='Interactions per hour')
    parser.add_argument('--duration', type=float, default=None,
                        help='Duration in hours for continuous mode')
    
    args = parser.parse_args()
    
    bot = TrainingBot(interactions_per_hour=args.speed)
    
    if args.mode == 'batch':
        bot.run_batch(count=args.count)
    else:
        bot.run_continuous(duration_hours=args.duration)


if __name__ == '__main__':
    main()
