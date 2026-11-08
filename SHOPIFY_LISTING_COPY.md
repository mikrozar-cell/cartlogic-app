# Shopify App Store Listing Copy — CartLogic Order & Quantity Limits

## 1. Basic App Information
- **App Name:** `CartLogic Order Limits` *(or `CartLogic — Order & Quantity Limits`)*
- **App Icon:** `cartlogic_icon_1200x1200.png` (1200x1200 px, zero text)
- **Primary Category:** `Selling products > Checkout > Order limits` *(or `Cart customization`)*

## 2. Main Listing Content (Zero banned words / zero "price" triggers)
- **App Introduction (89 / 100 chars):**
  `Enforce min-max order quantities, case pack multiples, and B2B cart rules at checkout.`

- **App Details (468 / 500 chars):**
  `CartLogic enforces order quantity limits, case pack multiples, and subtotal bounds before checkout completion. Unlike legacy storefront script tools that buyers can bypass using express payment buttons, rules are compiled into store validation metadata and evaluated across standard and express checkouts. Configure per-product caps for limited releases, step multiples of 6 or 12 units for wholesale, and customer tag exemptions for B2B accounts.`

- **5 Key Features (Max 80 chars each):**
  1. `Enforce min and max quantity limits per product, SKU, or collection`
  2. `Require case pack step multiples such as packs of 6, 12, or 24 units`
  3. `Target rules by buyer segment including B2B wholesale tags or retail`
  4. `Interactive checkout validation simulator for testing cart constraints`
  5. `Blocks express payment bypasses across Shop Pay and Apple Pay flows`

## 3. Media & Alt Texts (1600x900 px, Zero pricing text, Alt text <= 64 chars)
1. `screenshot_1_validation_rules.png` (Used as Feature Image & Screenshot 1)
   - **Feature Image Alt text (52 chars):** `CartLogic validation rules table and checkout limits`
   - **Screenshot 1 Alt text (54 chars):** `Validation rules table and live checkout blocked alert`
2. `screenshot_2_checkout_allowed.png`
   - **Screenshot 2 Alt text (54 chars):** `Simulated cart with allowed checkout status and limits`
3. `screenshot_3_b2b_segment.png`
   - **Screenshot 3 Alt text (52 chars):** `B2B wholesale customer rules and protection settings`

## 4. Pricing Plan Details
- **Plan Name:** `Pro Validation` ($14.99 / month, 14-day free trial)
- **4 Top Features (Strictly <= 40 chars each):**
  1. `Unlimited checkout validation rules` (35 chars)
  2. `Case pack step multiple enforcement` (35 chars)
  3. `B2B & wholesale customer tag rules` (34 chars)
  4. `Live checkout validation simulator` (34 chars)

## 5. Discovery & Search
- **App Card Subtitle (58 / 62 chars):**
  `Min-max order quantities, case pack multiples & B2B limits`
- **Search Terms (5):**
  1. `order limits`
  2. `quantity limit`
  3. `min max order`
  4. `b2b wholesale`
  5. `cart validation`
- **SEO Title Tag (48 / 60 chars):**
  `CartLogic — Min Max Order & Quantity Limits`
- **SEO Meta Description (148 / 160 chars):**
  `Enforce min-max product quantities, wholesale case pack multiples, B2B order minimums, and limited release caps across standard and express checkout.`

## 6. URLs & Contact
- **Application URL:** `https://cartlogic-app.onrender.com`
- **Redirect URL:** `https://cartlogic-app.onrender.com/auth/callback`
- **Privacy Policy URL:** `https://cartlogic-app.onrender.com/privacy`
- **Support URL:** `https://cartlogic-app.onrender.com/support`
- **Support & Review Email:** `mikrozar@gmail.com`

## 7. Testing Instructions for Reviewer
```text
To test CartLogic — Order & Quantity Limits:
1. Open the embedded app inside your development store.
2. Review the 4 pre-configured validation rules in the Checkout Validation Rules table (Case Pack Multiple x6, Limited Release Max 2, B2B Wholesale Minimum Subtotal, and Sample Kit Cap).
3. In the right-hand "Live Checkout Validation Simulator", inspect how the current simulated cart triggers 2 checkout validation errors with exact JSON targets and remediation advice.
4. Click "Auto-Fix Cart Quantities" (or adjust item quantities with the +/- steppers) to see the validation state switch to "Checkout Permitted (ALLOW)".
5. Switch the "Simulated Buyer Profile" dropdown between "Retail Guest Visitor" and "B2B Account (tag: wholesale)" to verify segment-specific rule enforcement and exemptions.
6. Use the "Configure Validation Rule" composer on the left to create or edit any rule, and click "Sync to Checkout Edge" to compile and synchronize the validation rules JSON payload.
```

