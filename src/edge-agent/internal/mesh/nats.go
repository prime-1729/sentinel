package mesh

import (
	"log"

	"github.com/nats-io/nats.go"
)

// Client wraps the NATS connection
type Client struct {
	Conn *nats.Conn
}

// Connect initializes the connection to the NATS server
func Connect(url string) (*Client, error) {
	nc, err := nats.Connect(url)
	if err != nil {
		return nil, err
	}
	log.Printf("Connected to NATS at %s", nc.ConnectedUrl())
	return &Client{Conn: nc}, nil
}

// Close gracefully closes the NATS connection
func (c *Client) Close() {
	if c.Conn != nil {
		c.Conn.Close()
	}
}

// Publish broadcasts a message on a given topic
func (c *Client) Publish(subject string, data []byte) error {
	return c.Conn.Publish(subject, data)
}

// Subscribe listens to a given topic and executes the handler
func (c *Client) Subscribe(subject string, handler nats.MsgHandler) (*nats.Subscription, error) {
	return c.Conn.Subscribe(subject, handler)
}
