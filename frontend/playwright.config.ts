import { defineConfig } from '@playwright/test';
import { existsSync } from 'node:fs';
const macChrome='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const executablePath=process.env.CHROME_PATH||(existsSync(macChrome)?macChrome:undefined);
export default defineConfig({testDir:'./e2e',workers:1,timeout:30000,use:{baseURL:process.env.APP_URL||'http://127.0.0.1:8000',headless:true,launchOptions:{executablePath},screenshot:'only-on-failure',trace:'retain-on-failure'},reporter:[['list'],['json',{outputFile:'test-results/results.json'}]]});
