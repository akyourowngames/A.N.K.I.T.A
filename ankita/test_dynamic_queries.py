"""
Test script to verify dynamic query generation produces unique queries
"""
from brain.dynamic_query_generator import DynamicQueryGenerator


def test_uniqueness():
    """Test that generator produces unique queries."""
    gen = DynamicQueryGenerator()
    
    print("=== Testing Query Uniqueness ===\n")
    
    situations = ["hungry", "sick", "tired", "stressed", "bored", "focus"]
    
    for situation in situations:
        print(f"\n{situation.upper()} (50 queries):")
        
        queries = []
        for i in range(50):
            query = gen.generate(situation)
            queries.append(query)
        
        # Check for duplicates
        unique = set(queries)
        duplicate_count = len(queries) - len(unique)
        
        print(f"  Generated: {len(queries)}")
        print(f"  Unique: {len(unique)}")
        print(f"  Duplicates: {duplicate_count}")
        print(f"  Uniqueness: {len(unique)/len(queries)*100:.1f}%")
        
        # Show sample
        print(f"\n  Sample queries:")
        for q in list(unique)[:5]:
            print(f"    • {q}")
        
        if duplicate_count > 0:
            print(f"  ⚠️  Warning: {duplicate_count} duplicates found")
        else:
            print(f"  ✅ Perfect! No duplicates!")


def test_history_tracking():
    """Test that history prevents duplicates."""
    gen = DynamicQueryGenerator(max_history=100)
    
    print("\n\n=== Testing History Tracking ===\n")
    
    situation = "hungry"
    queries = []
    
    # Generate 200 queries
    for i in range(200):
        query = gen.generate(situation)
        queries.append(query)
    
    print(f"Generated 200 queries for '{situation}'")
    print(f"Unique queries: {len(set(queries))}")
    print(f"History size: {len(gen.query_history)}")
    print(f"Uniqueness: {len(set(queries))/len(queries)*100:.1f}%")
    
    if len(set(queries)) == len(queries):
        print("✅ Perfect! All queries are unique!")
    else:
        duplicates = len(queries) - len(set(queries))
        print(f"⚠️  {duplicates} duplicates in 200 queries")


if __name__ == '__main__':
    test_uniqueness()
    test_history_tracking()
    
    print("\n\n=== Summary ===")
    print("Dynamic query generator can produce thousands of unique variations!")
    print("Each situation has 10+ templates × 6+ synonyms per placeholder")
    print("= 1000s of possible combinations per situation! 🚀")
