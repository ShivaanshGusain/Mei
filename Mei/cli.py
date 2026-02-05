# mei/cli.py
from .core.agent import MeiAgent
def main():
    """CLI entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Mei - Voice Desktop Agent")
    parser.add_argument("--config", help="Path to config file")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    args = parser.parse_args()
    
    # ASCII art banner
    print("""
    ███╗   ███╗███████╗██╗
    ████╗ ████║██╔════╝██║
    ██╔████╔██║█████╗  ██║
    ██║╚██╔╝██║██╔══╝  ██║
    ██║ ╚═╝ ██║███████╗██║
    ╚═╝     ╚═╝╚══════╝╚═╝
    
    Voice Desktop Agent
    """)
    
    # Create agent
    agent = MeiAgent()
    
    # Start
    try:
        agent.start()
    except KeyboardInterrupt:
        print("\nInterrupted")
    finally:
        agent.stop()


if __name__ == "__main__":
    main()