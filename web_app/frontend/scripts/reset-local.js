#!/usr/bin/env node
// Simple script to clear browser storage for the app by visiting the app URL and clearing storage via Playwright

const { chromium } = require('playwright')

async function run() {
  const url = process.argv[2] || 'http://localhost:3000'
  console.log(`Opening ${url} to clear local storage...`)
  const browser = await chromium.launch()
  const context = await browser.newContext()
  const page = await context.newPage()
  try {
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 10000 })
    await page.evaluate(async () => {
      try {
        localStorage.clear()
      } catch (e) {}
      try {
        sessionStorage.clear()
      } catch (e) {}
      if (window.indexedDB && indexedDB.databases) {
        const dbs = await indexedDB.databases()
        for (const db of dbs) {
          try {
            await new Promise((res, rej) => {
              const req = indexedDB.deleteDatabase(db.name)
              req.onsuccess = () => res()
              req.onerror = () => res()
              req.onblocked = () => res()
            })
          } catch (e) {}
        }
      }
    })
    await context.clearCookies()
    console.log('Cleared localStorage, sessionStorage, indexedDB (if supported), and cookies.')
  } catch (err) {
    console.error('Error while trying to clear storage:', err.message)
  } finally {
    await browser.close()
  }
}

run()
