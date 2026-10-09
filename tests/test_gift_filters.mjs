
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
const visible = () => grid.cards.filter(card=>!card.hidden);
assert.equal(grid.cards[0].dataset.name, 'Café da manhã');
assert.equal(elements['kp-gift-count'].textContent, '3 presentes');
elements['kp-gift-search'].value = 'cafe';
elements['kp-gift-search'].fire('input');
assert.equal(visible().length, 1);
assert.equal(visible()[0].dataset.name, 'Café da manhã');
elements['kp-gift-search'].value='';
elements['kp-gift-search'].fire('input');
elements['kp-gift-budget'].value='250';
elements['kp-gift-budget'].fire('change');
assert.equal(visible().length, 2);
elements['kp-gift-sort'].value='desc';
elements['kp-gift-sort'].fire('change');
assert.equal(visible()[0].dataset.name,'Jantar romântico');
elements['kp-gift-sort'].value='name';
elements['kp-gift-sort'].fire('change');
assert.equal(visible()[0].dataset.name,'Café da manhã');
elements['kp-gift-search'].value='não existe';
elements['kp-gift-search'].fire('input');
assert.equal(visible().length,0);
assert.equal(elements['kp-gift-no-results'].hidden,false);
elements['kp-gift-reset'].fire('click');
assert.equal(visible().length,3);
assert.equal(elements['kp-gift-search'].focused,true);
assert.equal(elements['kp-gift-no-results'].hidden,true);
assert.equal(images[0].hidden,true);
assert.equal(fallback.hidden,false);
console.log('Gift filters: search, accents, budget, sorting, empty state, reset and image fallback passed.');
