"""
Training Dashboard - Monitor training bot progress
"""
import json
import os
from datetime import datetime
from brain.learning_db import get_db
from brain.hybrid_intelligence import get_hybrid_ai


def print_dashboard():
    """Print comprehensive training dashboard."""
    
    print("\n" + "="*60)
    print(" "*20 + "ANKITA TRAINING DASHBOARD")
    print("="*60)
    
    # Time
    print(f"\nCurrent Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Load training stats if available
    try:
        with open('training_log.json', 'r') as f:
            training_stats = json.load(f)
        
        print(f"\n--- Training Bot Stats ---")
        print(f"Started: {training_stats.get('start_time', 'N/A')}")
        print(f"Total Interactions: {training_stats.get('total_interactions', 0)}")
        print(f"Successes: {training_stats.get('successes', 0)}")
        print(f"Failures: {training_stats.get('failures', 0)}")
        
        total = training_stats.get('total_interactions', 0)
        if total > 0:
            success_rate = training_stats.get('successes', 0) / total * 100
            print(f"Success Rate: {success_rate:.1f}%")
    except FileNotFoundError:
        print(f"\n--- Training Bot Stats ---")
        print("Not started yet")
    
    # Database stats
    db = get_db()
    cursor = db.conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM action_history")
    total_actions = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM action_history WHERE success = 1")
    successful_actions = cursor.fetchone()[0]
    
    print(f"\n--- Database Stats ---")
    print(f"Total Actions Logged: {total_actions}")
    print(f"Successful Actions: {successful_actions}")
    if total_actions > 0:
        print(f"Overall Success Rate: {successful_actions/total_actions*100:.1f}%")
    
    # Recent actions by situation
    cursor.execute("""
        SELECT situation, COUNT(*) as count
        FROM action_history
        GROUP BY situation
        ORDER BY count DESC
        LIMIT 10
    """)
    
    print(f"\n--- Top Situations (by frequency) ---")
    for row in cursor.fetchall():
        situation_name = row[0] or "unknown"
        count = row[1] or 0
        print(f"  {situation_name:20} {count:>5} actions")
    
    # Learning system stats
    try:
        hybrid_ai = get_hybrid_ai()
        stats = hybrid_ai.get_combined_stats()
        
        print(f"\n--- Learning Systems ---")
        
        if 'rl' in stats and stats['rl']:
            rl_stats = stats['rl']
            print(f"Q-Learning:")
            print(f"  Q-values: {rl_stats.get('total_q_values', 0)}")
            print(f"  Explorations: {rl_stats.get('explorations', 0)}")
            print(f"  Exploitations: {rl_stats.get('exploitations', 0)}")
        
        if 'knn' in stats and stats['knn']:
            knn_stats = stats['knn']
            print(f"k-NN:")
            print(f"  Total actions: {knn_stats.get('total_actions', 0)}")
            print(f"  Unique situations: {knn_stats.get('unique_situations', 0)}")
        
        if 'meta' in stats and stats['meta']:
            meta_stats = stats['meta']
            print(f"Meta-Learning:")
            print(f"  Transfers: {meta_stats.get('total_transfers', 0)}")
            print(f"  Unique targets: {meta_stats.get('unique_targets', 0)}")
        
        if 'few_shot' in stats and stats['few_shot']:
            fs_stats = stats['few_shot']
            print(f"Few-Shot:")
            print(f"  Examples: {fs_stats.get('total_examples', 0)}")
            print(f"  Situations: {fs_stats.get('unique_situations', 0)}")
    except Exception as e:
        print(f"\n--- Learning Systems ---")
        print(f"Error loading stats: {e}")
    
    # Q-values table stats
    try:
        cursor.execute("SELECT COUNT(*) FROM q_values")
        q_count = cursor.fetchone()[0]
        
        if q_count > 0:
            cursor.execute("""
                SELECT action, AVG(q_value) as avg_q
                FROM q_values
                GROUP BY action
                ORDER BY avg_q DESC
                LIMIT 5
            """)
            
            print(f"\n--- Top Q-Values (best actions) ---")
            for row in cursor.fetchall():
                print(f"  {row[0]:30} Q = {row[1]:.3f}")
    except:
        pass
    
    print("\n" + "="*60 + "\n")


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Ankita Training Dashboard')
    parser.add_argument('--watch', action='store_true',
                        help='Continuously watch and update')
    parser.add_argument('--interval', type=int, default=5,
                        help='Update interval in seconds for watch mode')
    
    args = parser.parse_args()
    
    if args.watch:
        import time
        print("Watch mode - Press Ctrl+C to stop")
        try:
            while True:
                os.system('cls' if os.name == 'nt' else 'clear')
                print_dashboard()
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\nStopped.")
    else:
        print_dashboard()


if __name__ == '__main__':
    main()
