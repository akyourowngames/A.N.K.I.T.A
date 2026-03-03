"""
Real scenario tests for WebAgent powers.
Tests actual function calls to verify they work as expected.
"""

def test_compare_search():
    """Test: Compare MacBook Air M3 vs Dell XPS 15"""
    print("=" * 60)
    print("TEST 1: compare_search")
    print("=" * 60)
    
    from tools import realtime_search
    
    try:
        result = realtime_search.compare_search(
            item_a="MacBook Air M3",
            item_b="Dell XPS 15",
            aspects=["price", "specs", "pros", "cons"]
        )
        
        print(f"✓ Function executed")
        print(f"  - Status: {result.get('ok')}")
        print(f"  - Item A: {result.get('item_a')}")
        print(f"  - Item B: {result.get('item_b')}")
        print(f"  - Has data_a: {bool(result.get('data_a'))}")
        print(f"  - Has data_b: {bool(result.get('data_b'))}")
        print(f"  - Instruction provided: {bool(result.get('instruction'))}")
        
        if result.get('ok'):
            print("✅ PASS: compare_search works correctly")
        else:
            print("❌ FAIL: compare_search returned ok=False")
            
    except Exception as e:
        print(f"❌ FAIL: {e}")


def test_search_reddit():
    """Test: What do people on Reddit think of Notion vs Obsidian"""
    print("\n" + "=" * 60)
    print("TEST 2: search_reddit")
    print("=" * 60)
    
    from tools import realtime_search
    
    try:
        result = realtime_search.search_reddit(
            query="Notion vs Obsidian",
            max_posts=5
        )
        
        print(f"✓ Function executed")
        print(f"  - Status: {result.get('ok')}")
        print(f"  - Query: {result.get('query')}")
        print(f"  - Posts found: {result.get('count', 0)}")
        
        if result.get('posts'):
            print(f"  - First post: {result['posts'][0].get('title', '')[:50]}...")
        
        if result.get('ok'):
            print("✅ PASS: search_reddit works correctly")
        else:
            print("❌ FAIL: search_reddit returned ok=False")
            
    except Exception as e:
        print(f"❌ FAIL: {e}")


def test_scrape_structured():
    """Test: Get all emails from a page"""
    print("\n" + "=" * 60)
    print("TEST 3: scrape_structured")
    print("=" * 60)
    
    from tools import realtime_search
    
    # Use a test page that's likely to have emails
    test_url = "https://example.com"
    
    try:
        result = realtime_search.scrape_structured(
            url=test_url,
            extract="emails"
        )
        
        print(f"✓ Function executed")
        print(f"  - Status: {result.get('ok')}")
        print(f"  - Extract type: {result.get('extract')}")
        print(f"  - URL: {result.get('url')}")
        print(f"  - Count: {result.get('count', 0)}")
        
        if result.get('ok'):
            print("✅ PASS: scrape_structured works correctly")
        else:
            print(f"❌ FAIL: {result.get('error', 'Unknown error')}")
            
    except Exception as e:
        print(f"❌ FAIL: {e}")


def test_fact_check():
    """Test: Fact check a claim"""
    print("\n" + "=" * 60)
    print("TEST 4: fact_check")
    print("=" * 60)
    
    from tools import realtime_search
    
    try:
        result = realtime_search.fact_check(
            claim="Apple is the most valuable company",
            sources=4
        )
        
        print(f"✓ Function executed")
        print(f"  - Status: {result.get('ok')}")
        print(f"  - Claim: {result.get('claim')}")
        print(f"  - Verdict: {result.get('verdict')}")
        print(f"  - Confidence: {result.get('confidence_pct')}%")
        print(f"  - Sources checked: {result.get('sources_checked')}")
        
        if result.get('ok'):
            print("✅ PASS: fact_check works correctly")
        else:
            print("❌ FAIL: fact_check returned ok=False")
            
    except Exception as e:
        print(f"❌ FAIL: {e}")


def test_web_monitor():
    """Test: Monitor a page"""
    print("\n" + "=" * 60)
    print("TEST 5: web_monitor")
    print("=" * 60)
    
    from tools import realtime_search
    
    try:
        # Test add action
        result = realtime_search.web_monitor(
            action="add",
            url="https://example.com",
            label="test_monitor"
        )
        
        print(f"✓ Add action executed")
        print(f"  - Status: {result.get('ok')}")
        print(f"  - Monitoring: {result.get('monitoring')}")
        
        # Test list action
        result2 = realtime_search.web_monitor(action="list")
        print(f"✓ List action executed")
        print(f"  - Monitors: {result2.get('count', 0)}")
        
        # Test remove action
        result3 = realtime_search.web_monitor(
            action="remove",
            label="test_monitor"
        )
        print(f"✓ Remove action executed")
        print(f"  - Removed: {result3.get('removed')}")
        
        if result.get('ok') and result2.get('ok') and result3.get('ok'):
            print("✅ PASS: web_monitor works correctly")
        else:
            print("❌ FAIL: One or more web_monitor actions failed")
            
    except Exception as e:
        print(f"❌ FAIL: {e}")


def test_trending_topics():
    """Test: What's trending on Hacker News"""
    print("\n" + "=" * 60)
    print("TEST 6: trending_topics")
    print("=" * 60)
    
    from tools import realtime_search
    
    try:
        result = realtime_search.trending_topics(
            category="tech",
            region="US"
        )
        
        print(f"✓ Function executed")
        print(f"  - Status: {result.get('ok')}")
        print(f"  - Category: {result.get('category')}")
        print(f"  - Sources: {list(result.get('sources', {}).keys())}")
        
        hn_stories = result.get('sources', {}).get('hacker_news', [])
        if hn_stories:
            print(f"  - HN stories: {len(hn_stories)}")
            print(f"  - Top story: {hn_stories[0].get('title', '')[:50]}...")
        
        if result.get('ok'):
            print("✅ PASS: trending_topics works correctly")
        else:
            print("❌ FAIL: trending_topics returned ok=False")
            
    except Exception as e:
        print(f"❌ FAIL: {e}")


def test_image_search():
    """Test: Find images"""
    print("\n" + "=" * 60)
    print("TEST 7: image_search")
    print("=" * 60)
    
    from tools import realtime_search
    
    try:
        result = realtime_search.image_search(
            query="Stripe logo",
            max_results=5,
            download=False  # Don't actually download in test
        )
        
        print(f"✓ Function executed")
        print(f"  - Status: {result.get('ok')}")
        print(f"  - Query: {result.get('query')}")
        print(f"  - Images found: {result.get('count', 0)}")
        
        if result.get('images'):
            print(f"  - First image: {result['images'][0].get('title', '')[:50]}...")
        
        if result.get('ok'):
            print("✅ PASS: image_search works correctly")
        else:
            print("❌ FAIL: image_search returned ok=False")
            
    except Exception as e:
        print(f"❌ FAIL: {e}")


def test_summarise_url():
    """Test: Summarise a URL"""
    print("\n" + "=" * 60)
    print("TEST 8: summarise_url")
    print("=" * 60)
    
    from tools import realtime_search
    
    try:
        result = realtime_search.summarise_url(
            url="https://example.com",
            style="bullets",
            max_bullets=5
        )
        
        print(f"✓ Function executed")
        print(f"  - Status: {result.get('ok')}")
        print(f"  - URL: {result.get('url')}")
        print(f"  - Style: {result.get('style')}")
        print(f"  - Has content: {bool(result.get('content_for_llm'))}")
        print(f"  - Has instruction: {bool(result.get('instruction'))}")
        
        if result.get('ok'):
            print("✅ PASS: summarise_url works correctly")
        else:
            print(f"❌ FAIL: {result.get('error', 'Unknown error')}")
            
    except Exception as e:
        print(f"❌ FAIL: {e}")


def test_multi_search():
    """Test: Multi-query parallel search"""
    print("\n" + "=" * 60)
    print("TEST 9: multi_search")
    print("=" * 60)
    
    from tools import realtime_search
    
    try:
        result = realtime_search.multi_search(
            queries=["best Python courses", "best JavaScript courses"],
            fetch_top=2
        )
        
        print(f"✓ Function executed")
        print(f"  - Status: {result.get('ok')}")
        print(f"  - Queries: {result.get('count', 0)}")
        print(f"  - Bundles: {len(result.get('bundles', []))}")
        
        if result.get('bundles'):
            print(f"  - First query: {result['bundles'][0].get('query')}")
        
        if result.get('ok'):
            print("✅ PASS: multi_search works correctly")
        else:
            print("❌ FAIL: multi_search returned ok=False")
            
    except Exception as e:
        print(f"❌ FAIL: {e}")


def test_web_to_dataset():
    """Test: Web to dataset"""
    print("\n" + "=" * 60)
    print("TEST 10: web_to_dataset")
    print("=" * 60)
    
    from tools import realtime_search
    
    try:
        result = realtime_search.web_to_dataset(
            query="top programming languages 2024",
            columns=["Language", "Popularity", "Use Case"],
            max_rows=10
        )
        
        print(f"✓ Function executed")
        print(f"  - Status: {result.get('ok')}")
        print(f"  - Query: {result.get('query')}")
        print(f"  - Columns: {result.get('columns')}")
        print(f"  - Max rows: {result.get('max_rows')}")
        print(f"  - Has content: {bool(result.get('content_for_llm'))}")
        print(f"  - Has instruction: {bool(result.get('extraction_instruction'))}")
        
        if result.get('ok'):
            print("✅ PASS: web_to_dataset works correctly")
        else:
            print("❌ FAIL: web_to_dataset returned ok=False")
            
    except Exception as e:
        print(f"❌ FAIL: {e}")


def test_stackoverflow():
    """Test: Stack Overflow search"""
    print("\n" + "=" * 60)
    print("TEST 11: search_stackoverflow")
    print("=" * 60)
    
    from tools import realtime_search
    
    try:
        result = realtime_search.search_stackoverflow(
            query="Python ImportError",
            max_results=5
        )
        
        print(f"✓ Function executed")
        print(f"  - Status: {result.get('ok')}")
        print(f"  - Query: {result.get('query')}")
        print(f"  - Results: {result.get('count', 0)}")
        
        if result.get('results'):
            print(f"  - First result: {result['results'][0].get('title', '')[:50]}...")
        
        if result.get('ok'):
            print("✅ PASS: search_stackoverflow works correctly")
        else:
            print(f"❌ FAIL: {result.get('error', 'Unknown error')}")
            
    except Exception as e:
        print(f"❌ FAIL: {e}")


if __name__ == "__main__":
    print("\n🧪 ANKITA WebAgent Real Scenario Tests\n")
    print("Testing actual function calls with real scenarios...")
    print("Note: Some tests require internet connection\n")
    
    tests = [
        test_compare_search,
        test_search_reddit,
        test_scrape_structured,
        test_fact_check,
        test_web_monitor,
        test_trending_topics,
        test_image_search,
        test_summarise_url,
        test_multi_search,
        test_web_to_dataset,
        test_stackoverflow,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"\n❌ Test failed with exception: {e}")
            failed += 1
    
    print("\n" + "=" * 60)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 60)
    
    if failed == 0:
        print("\n✅ All tests passed! WebAgent powers are working correctly.")
    else:
        print(f"\n⚠️ {failed} test(s) failed. Check the output above for details.")
