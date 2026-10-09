import http from 'node:http';

const CALENDAR_BUTTON_COUNT = 180; // Test-only: deliberately exceed the production 160-control observation cap.
const FIXTURE_AIRPORTS = Object.freeze([{ city: 'Mumbai', code: 'BOM' }, { city: 'New Delhi', code: 'DEL' }]); // Independent synthetic flight oracle; never production routing truth.

function flightPage(departureDate) {
  return `<!doctype html><meta charset="utf-8"><title>Flight search fixture</title>
  <h1>Find a flight</h1><p>Popular route: New Delhi to Mumbai. Suggestions are not your requested itinerary.</p>
  <form><button type="button" role="combobox" id="trip">Round trip</button>
  <label>Origin <input role="combobox" id="origin" readonly value="New Delhi (DEL)"></label>
  <label>Destination <input role="combobox" id="destination" readonly value="Mumbai (BOM)"></label>
  <label>Departure <input id="departure" readonly></label><button id="search">Search flights</button></form>
  <main id="results"></main><div id="picker"></div>
  <script>
  const airports=${JSON.stringify(FIXTURE_AIRPORTS)}, requestedDate=${JSON.stringify(departureDate)};
  const state={origin:'DEL',destination:'BOM',trip:'Round trip',date:''};
  const picker=document.getElementById('picker');
  function airportPicker(kind){
    picker.innerHTML='<div role="dialog" aria-label="Enter '+kind+'"><label>Search '+kind+' <input id="airport-text"></label><div id="options" role="listbox"></div></div>';
    const input=document.getElementById('airport-text');
    const update=()=>{
      const options=document.getElementById('options');options.replaceChildren();
      for(const airport of airports.filter(a=>(a.city+' '+a.code).toLowerCase().includes(input.value.toLowerCase()))){
        const button=document.createElement('button');button.setAttribute('role','option');button.textContent=airport.city+' ('+airport.code+')';
        button.onclick=()=>{state[kind]=airport.code;document.getElementById(kind).value=button.textContent;picker.replaceChildren();};options.append(button);
      }
    };input.oninput=update;update();input.focus();
  }
  for(const kind of ['origin','destination'])document.getElementById(kind).onclick=()=>airportPicker(kind);
  document.getElementById('trip').onclick=()=>{
    picker.innerHTML='<div role="listbox"><button role="option">One way</button></div>';
    picker.querySelector('button').onclick=()=>{state.trip='One way';document.getElementById('trip').textContent=state.trip;picker.replaceChildren();};
  };
  document.getElementById('departure').onclick=()=>{
    picker.innerHTML='<div role="dialog" aria-label="Departure calendar"><h2>Departure calendar</h2></div>';
    const dialog=picker.firstElementChild;
    for(let i=0;i<${CALENDAR_BUTTON_COUNT};i++){
      const date=new Date(requestedDate+'T12:00:00Z');date.setUTCDate(date.getUTCDate()+i);
      const iso=date.toISOString().slice(0,10),button=document.createElement('button');
      button.textContent=new Intl.DateTimeFormat('en-GB',{day:'numeric',month:'long',year:'numeric',timeZone:'UTC'}).format(date);
      button.onclick=()=>{state.date=iso;document.getElementById('departure').value=iso;};dialog.append(button);
    }
    const done=document.createElement('button');done.textContent='Done';done.onclick=()=>picker.replaceChildren();dialog.append(done);
  };
  document.querySelector('form').onsubmit=async event=>{
    event.preventDefault();
    const response=await fetch('/search',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(state)});
    const data=await response.json();document.getElementById('results').innerHTML='<h2>Flight results</h2><p>'+data.origin+' → '+data.destination+' | '+data.trip+' | '+data.date+'</p><p>Fixture fare only. No reservation or payment.</p>';
  };
  </script>`;
}

export async function createFlightFixtureServer({ departureDate }) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(departureDate)) throw new Error('Fixture requires an ISO departure date');
  const searches = [];
  const server = http.createServer((request, response) => {
    if (request.url === '/search' && request.method === 'POST') {
      let text = '';
      request.on('data', chunk => { text += chunk; });
      request.on('end', () => {
        const state = JSON.parse(text); searches.push(state);
        const city = code => FIXTURE_AIRPORTS.find(airport => airport.code === code)?.city + ` (${code})`;
        response.writeHead(200, { 'content-type': 'application/json' });
        response.end(JSON.stringify({ ...state, origin: city(state.origin), destination: city(state.destination) }));
      });
    } else {
      response.writeHead(200, { 'content-type': 'text/html; charset=utf-8' }); response.end(flightPage(departureDate));
    }
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  return { searches, url: `http://127.0.0.1:${server.address().port}/`, async close() {
    server.closeAllConnections(); await new Promise(resolve => server.close(resolve));
  } };
}
