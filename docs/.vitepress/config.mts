import { defineConfig } from 'vitepress'
import { tabsMarkdownPlugin } from 'vitepress-plugin-tabs'
import fs from 'fs'
import path from 'path'

const siteTitle = "AgentSight.io";
const siteDesc = "Seamlessly track AI conversations, metrics, and deliver client-facing insights and dashboards.";
const siteUrl = "https://docs.agentsight.io";
const ogImage = `${siteUrl}/images/opengraph-image.png`;

export default defineConfig({
  base: '/',
  title: siteTitle,
  description: siteDesc,
  async transformPageData(pageData) {
    if (!pageData.relativePath) return
  
    const filePath = path.join(process.cwd(), pageData.relativePath)
  
    const extended = pageData as typeof pageData & { raw?: string }
  
    try {
      extended.raw = fs.readFileSync(filePath, 'utf-8')
    } catch (err) {
      console.warn('[copy-md] Could not read markdown file:', filePath)
    }
  },
  head: [
    // Open Graph
    ['meta', { property: 'og:type', content: 'website' }],
    ['meta', { property: 'og:title', content: siteTitle }],
    ['meta', { property: 'og:description', content: siteDesc }],
    ['meta', { property: 'og:url', content: siteUrl }],
    ['meta', { property: 'og:image', content: `${siteUrl}/images/opengraph-image.png` }],
    ['meta', { property: 'og:site_name', content: siteTitle }],
    ['meta', { property: 'og:image', content: ogImage }],
    ['meta', { property: 'og:image:secure_url', content: ogImage }],
    ['meta', { property: 'og:image:type', content: 'image/png' }],
    ['meta', { property: 'og:image:width', content: '1260' }],
    ['meta', { property: 'og:image:height', content: '630' }],
    ['meta', { property: 'og:image:alt', content: 'AgentSight Documentation Preview Image' }],

    // Twitter (X) Card
    ['meta', { name: 'twitter:card', content: 'summary_large_image' }],
    ['meta', { name: 'twitter:title', content: siteTitle }],
    ['meta', { name: 'twitter:description', content: siteDesc }],
    ['meta', { name: 'twitter:image', content: `${siteUrl}/images/opengraph-image.png` }],
    ['link', { rel: 'icon', href: '/images/favicon.ico' }]
  ],
  markdown: {
    config(md) {
      md.use(tabsMarkdownPlugin)
    }
  },
  themeConfig: {
    logo: {
      light: '/images/agentsight_logo_black.svg',
      dark:'/images/agentsight_logo_white.svg'
    },
    siteTitle: false,
    nav: [
      { text: 'Home', link: '/' },
      { text: 'Quick Start', link: '/getting-started/quick-start' },
      { text: 'REST API reference', link: '/getting-started/api-reference' }
    ],

    sidebar: [
      {
        text: 'Getting Started',
        collapsed: false,
        items: [
          { text: 'Quickstart', link: '/getting-started/quick-start' },
          { text: 'Use with AI agents', link: '/getting-started/ai-agents' },
          { text: 'Core Concepts', link: '/getting-started/core-concepts' },
          { text: 'Metrics', link: '/getting-started/metrics' },
          { text: 'Configuration', link: '/getting-started/configuration' },
          { text: 'What gets traced & why', link: '/getting-started/what-gets-traced' },
          { text: 'What the SDK sends', link: '/getting-started/what-the-sdk-sends' },
          { text: 'Environments', link: '/getting-started/environments' },
          { text: 'Deployment & limitations', link: '/getting-started/deployment' },
          { text: 'REST API reference', link: '/getting-started/api-reference' }
        ]
      },
      {
        text: 'Tracking',
        collapsed: false,
        items: [
          { text: 'Conversations', link: '/tracking/conversations' },
          { text: 'Turns & Messages', link: '/tracking/turns-and-messages' },
          { text: 'Streaming', link: '/tracking/streaming' },
          { text: 'Tools & Actions', link: '/tracking/tools-and-actions' },
          { text: 'Tokens & Cost', link: '/tracking/tokens-and-cost' },
          { text: 'Buttons', link: '/tracking/buttons' },
          { text: 'Attachments', link: '/tracking/attachments' },
        ]
      },
      {
        text: 'Integrations',
        collapsed: false,
        items: [
          { text: 'OpenAI', link: '/integrations/openai' },
          { text: 'Anthropic', link: '/integrations/anthropic' },
          { text: 'LlamaIndex', link: '/integrations/llamaindex' },
          { text: 'LangChain', link: '/integrations/langchain' },
          { text: 'Other providers', link: '/integrations/other-providers' },
          { text: 'FastAPI', link: '/integrations/fastapi' },
        ]
      },
      {
        text: 'Examples',
        collapsed: false,
        items: [
          { text: 'Overview', link: '/examples/' },
          { text: 'The SDK on its own', link: '/examples/plain' },
          { text: 'OpenAI', link: '/examples/openai' },
          { text: 'Anthropic', link: '/examples/anthropic' },
          { text: 'LlamaIndex', link: '/examples/llamaindex' },
          { text: 'LangChain', link: '/examples/langchain' },
          { text: 'Streaming & wrap()', link: '/examples/streaming' },
        ]
      },
      {
        text: 'API Client',
        collapsed: false,
        items: [
          { text: 'The API client', link: '/api/' },
          { text: 'Conversations', link: '/api/conversations' },
          { text: 'Feedbacks', link: '/api/feedbacks' },
          { text: 'Tickets', link: '/api/tickets' },
          { text: 'Actions', link: '/api/actions' },
          { text: 'Usage', link: '/api/usage' },
          { text: 'Spans', link: '/api/spans' },
          { text: 'Pagination', link: '/api/pagination' },
          { text: 'Errors & retries', link: '/api/errors' },
        ]
      }
    ],

    search: {
      provider: 'local'
    },

    socialLinks: [
      { icon: 'github', link: 'https://github.com/agentsightio/agentsightio' }
    ]
  }
})
