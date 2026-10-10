
const assert = (await import('node:assert/strict')).default;


function input(value = '') {
  return {value, listeners: {}, addEventListener(type, callback) { this.listeners[type] = callback; }, fire(type) { this.listeners[type]?.(); }, focus() { this.focused = true; }};
}
const cards = [
  {dataset: {name:'Jantar romântico', price:'189.9'}},
  {dataset: {name:'Café da manhã', price:'89.9'}},
  {dataset: {name:'Viagem', price:'899.9'}}
];
const images = [{complete:true, naturalWidth:0, listeners:{}, addEventListener(type, cb){this.listeners[type]=cb;}, parentElement:{querySelector(){return fallback;}}}];
const fallback = {hidden:true};
const grid = {cards:[...cards], querySelectorAll(selector){return selector === '.kp-gift-card' ? this.cards : images;}, appendChild(card){this.cards.splice(this.cards.indexOf(card),1);this.cards.push(card);}};
const elements = {
  'kp-gift-grid': grid, 'kp-gift-search': input(), 'kp-gift-budget': input('all'),
  'kp-gift-sort': input('default'), 'kp-gift-count': {}, 'kp-gift-no-results': {hidden:true},
  'kp-gift-reset': input()
};
const context = {
  document: {body: {}, querySelector(){return null;}, querySelectorAll(){return [];}, getElementById(id){return elements[id];}, addEventListener(event, cb){if(event === 'DOMContentLoaded') cb();}},
  window: {matchMedia(){return {matches:true};}},
};
global.document = context.document;
global.window = context.window;
await import('../app/static/js/app.js');
assert.equal(images[0].hidden,true);
assert.equal(fallback.hidden,false);
console.log('Gift image fallback passed.');
